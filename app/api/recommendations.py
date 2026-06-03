"""
Product recommendation endpoint.

Combines body measurements + questionnaire answers + product catalog
and asks the LLM for personalized recommendations in Persian.
"""
import json
import logging
import re
import traceback
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.core.dependencies import get_current_active_user
from app.services.product_service import product_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# Cap how much of any single user-supplied value we ever interpolate into a
# prompt — protects against runaway tokens and pads against trivial injection.
_MAX_FIELD_LEN = 200
_MAX_PRODUCTS_IN_PROMPT = 10
_PRODUCT_PICK_LIMIT = 5
_MAX_PRODUCTS_PER_TYPE = 8   # per-type fetch limit in multi-product mode
_PICK_LIMIT_PER_TYPE = 3     # LLM picks per product type in multi-product mode


class RecommendationRequest(BaseModel):
    upload_id: Optional[str] = None


class SizeRecommendationRequest(BaseModel):
    upload_id: str
    available_sizes: list[str] = []


METADATA_DIR = settings.media_path / "metadata"


def _load_metadata(upload_id: str) -> Optional[dict]:
    path = METADATA_DIR / f"{upload_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _list_user_metadata(user_id: str) -> list[dict]:
    if not METADATA_DIR.exists():
        return []
    uploads = []
    for p in METADATA_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if str(data.get("user_id")) == str(user_id):
                uploads.append(data)
        except Exception:
            continue
    uploads.sort(key=lambda u: u.get("uploaded_at", ""), reverse=True)
    return uploads


def _extract_average_measurements(upload: dict) -> dict:
    """Return the best measurement dict (Consensus > Average > last)."""
    results = upload.get("processing_results") or {}
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except (json.JSONDecodeError, TypeError):
            return {}
    measurements_list = results.get("measurements", [])
    # Prefer Consensus, then Average, then last entry
    for preferred in ("Consensus", "Average"):
        for entry in measurements_list:
            if entry.get("label") == preferred:
                return entry.get("results", {})
    if measurements_list:
        return measurements_list[-1].get("results", {})
    return {}


def _safe(value: Any, max_len: int = _MAX_FIELD_LEN) -> str:
    """Render a value for prompt interpolation.

    Strips newlines, backticks, and prompt-delimiter sequences so a
    questionnaire answer can't break out of its template slot. Truncates to
    `max_len` characters.
    """
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "بله" if value else "خیر"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    # Strip control chars + collapse whitespace
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    # Neutralize delimiters the model treats specially
    text = text.replace("```", "´´´").replace("`", "´")
    text = re.sub(r"<\|.*?\|>", "", text)
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text or "-"


def _build_prefs_block(
    answers: dict,
    product_answers_map: dict,
    garment_types: list[str],
) -> str:
    """Build a preferences summary from flat or multi-product answers."""
    # Collect values from all product type answers + flat answers
    def _collect(key: str) -> str:
        vals: set = set()
        # From flat answers
        v = answers.get(key)
        if v:
            if isinstance(v, list):
                vals.update(str(x) for x in v if x)
            elif str(v) != "-":
                vals.add(str(v))
        # From per-type answers
        for pa in product_answers_map.values():
            v = pa.get(key)
            if v:
                if isinstance(v, list):
                    vals.update(str(x) for x in v if x)
                elif str(v) != "-":
                    vals.add(str(v))
        return "، ".join(vals) if vals else ""

    block = ""
    style_val = _collect("style")
    if style_val:
        block += f"\nاستایل ترجیحی: {_safe(style_val)}"
    occasion_val = _collect("occasion")
    if occasion_val:
        block += f"\nمناسبت: {_safe(occasion_val)}"
    season_val = _collect("season")
    if season_val:
        block += f"\nفصل: {_safe(season_val)}"
    colors_val = _collect("colors")
    if colors_val:
        block += f"\nرنگ مورد نظر: {_safe(colors_val)}"
    pattern_val = _collect("pattern")
    if pattern_val:
        block += f"\nطرح: {_safe(pattern_val)}"
    usage_val = _collect("usage")
    if usage_val:
        block += f"\nکاربرد: {_safe(usage_val)}"
    weave_val = _collect("weave")
    if weave_val:
        block += f"\nبافت: {_safe(weave_val)}"
    return block


def _format_products_for_prompt(products: list[dict]) -> str:
    """Render products as a numbered list. Indices are 1-based."""
    lines = []
    for idx, p in enumerate(products, start=1):
        title = _safe(p.get("title") or p.get("name_fa") or p.get("name") or "?", 80)
        price = p.get("price", 0)
        price_str = f"{price:,}" if isinstance(price, (int, float)) and price else "-"
        category = _safe(p.get("category", "-"), 40)
        brand = _safe(p.get("brand") or "-", 40)
        specs = p.get("specifications", {}) or {}
        specs_str = (
            "، ".join(f"{_safe(k, 30)}: {_safe(v, 60)}" for k, v in specs.items())
            if specs else "-"
        )
        # Include product type tag if available (multi-product mode)
        type_tag = ""
        req_type = p.get("_requested_type")
        if req_type:
            type_tag = f" [نوع: {_safe(req_type, 40)}]"

        # Include size/variant info
        variants = p.get("variants") or []
        sizes_available = set()
        for v in variants:
            attrs = v.get("attributes") or {}
            for gname, aval in attrs.items():
                if "اندازه" in gname.lower() or "size" in gname.lower():
                    if v.get("in_stock", True):
                        sizes_available.add(aval)
        size_str = f" | سایزهای موجود: {', '.join(sorted(sizes_available))}" if sizes_available else ""

        lines.append(
            f"{idx}. {title}{type_tag} | قیمت: {price_str} تومان | "
            f"دسته: {category} | برند: {brand}{size_str} | مشخصات: {specs_str}"
        )
    return "\n".join(lines)


def _build_prompt(
    measurements: dict,
    answers: dict,
    products: list[dict],
    calculated_size: str = "",
    pick_limit: int = _PRODUCT_PICK_LIMIT,
) -> str:
    """Build a Persian prompt for the LLM that asks for a JSON pick list."""
    meas_text = "\n".join(
        f"- {_safe(k, 40)}: {_safe(v, 40)}" for k, v in measurements.items() if v
    ) or "-"

    # ── Build answers text — handle multi-product format ──
    product_answers_map = answers.get("productAnswers") or {}
    garment_types = answers.get("garmentTypes") or answers.get("fabricTypes") or []
    is_multi = bool(garment_types and product_answers_map)

    if is_multi:
        base_lines = []
        for k, v in answers.items():
            if k in ("productAnswers", "garmentTypes", "fabricTypes"):
                continue
            base_lines.append(f"- {_safe(k, 40)}: {_safe(v)}")
        base_lines.append(f"- انواع محصول درخواستی: {', '.join(garment_types)}")
        answers_text = "\n".join(base_lines)

        answers_text += "\n\nترجیحات مشتری به تفکیک نوع محصول:"
        for ptype_slug in garment_types:
            pa = product_answers_map.get(ptype_slug, {})
            answers_text += f"\n  «{ptype_slug}»:"
            if pa:
                for pk, pv in pa.items():
                    answers_text += f"\n    - {_safe(pk, 40)}: {_safe(pv)}"
            else:
                answers_text += "\n    (بدون ترجیح خاص)"
    else:
        answers_text = "\n".join(
            f"- {_safe(k, 40)}: {_safe(v)}" for k, v in answers.items()
        ) or "-"

    # ── Build products text with type tags ──
    products_text = _format_products_for_prompt(products)
    n = min(len(products), len(products))  # actual number shown

    size_line = f"\nسایز محاسبه‌شده: {calculated_size}" if calculated_size else ""

    # ── Build preferences block from flat or aggregated per-type answers ──
    prefs_block = _build_prefs_block(answers, product_answers_map, garment_types)

    # ── Determine role ──
    category = answers.get("category", "")
    is_fabric = category.lower() in ("fabric", "پارچه")
    role_desc = "مشاور پارچه و منسوجات" if is_fabric else "مشاور لباس و استایلیست شخصی"

    # ── Multi-product instruction addition ──
    multi_instruction = ""
    if is_multi:
        types_str = "، ".join(f"«{t}»" for t in garment_types)
        multi_instruction = f"""
نکته مهم: مشتری به دنبال چند نوع محصول مختلف است: {types_str}
تلاش کن برای هر نوع محصول درخواستی حداقل یک پیشنهاد از لیست داشته باشی.
محصولات را با هم ست کن و توضیح بده چگونه با هم ترکیب می‌شوند."""

    return f"""تو یک {role_desc} حرفه‌ای و باتجربه هستی که در یک فروشگاه معتبر کار می‌کنی. مشتری به تو مراجعه کرده و اطلاعات زیر را داده. تو باید مثل یک فروشنده واقعی و دلسوز، بهترین محصولات را از لیست موجودی فروشگاه انتخاب کنی و یک مشاوره خرید کامل و حرفه‌ای ارائه بدی.
{multi_instruction}
--- پروفایل مشتری ---

اندازه‌های بدن:
{meas_text}{size_line}

ترجیحات و سلیقه:{prefs_block}

پاسخ‌های پرسشنامه:
{answers_text}

--- موجودی فروشگاه ---
{products_text}

--- دستورالعمل خروجی ---

خط اول: یک شیء JSON به شکل {{"picks": [شماره‌ها]}} — حداکثر {pick_limit} شماره از ۱ تا {n}.

سپس یک متن مشاوره خرید فارسی بنویس. متن باید دقیقاً شبیه صحبت یک فروشنده حرفه‌ای در فروشگاه باشد:

بخش ۱ — خوشامدگویی:
یک جمله کوتاه و صمیمی خوشامدگویی.

بخش ۲ — معرفی محصولات پیشنهادی:
برای هر محصول انتخاب‌شده:
- نام محصول و برندش را ذکر کن
- بگو چرا برای اندام و سایز مشتری مناسب است (با اشاره به اندازه‌های بدن)
- بگو چرا با استایل و سلیقه مشتری هماهنگ است
- بگو برای چه مناسبت‌ها و فصل‌هایی ایده‌آل است
- اگر قیمت مناسبی دارد، به آن اشاره کن

بخش ۳ — پیشنهاد ست و ترکیب:
توضیح بده چگونه محصولات پیشنهادی را می‌توان با هم ست کرد. مثلاً این پیراهن با آن شلوار و این کفش یک تیپ کامل می‌سازد. اگر مشتری چند نوع محصول خواسته، نشان بده چطور همه با هم هماهنگ می‌شوند.

بخش ۴ — اکسسوری و مکمل‌ها:
پیشنهاد اکسسوری‌ها و لوازم مکمل مثل کمربند، کفش، ساعت، کیف و غیره. حتی اگر در فروشگاه موجود نیستند، پیشنهاد بده.

بخش ۵ — نکات نگهداری:
یک یا دو نکته کوتاه درباره نگهداری و شستشوی محصولات.

بخش ۶ — جمع‌بندی:
یک جمله پایانی دلگرم‌کننده.

قوانین نوشتار:
- کل متن فارسی باشد
- لحن صمیمی و حرفه‌ای — مثل یک فروشنده واقعی
- حتماً از نام واقعی محصولات، برندها و ویژگی‌های موجود در لیست فروشگاه استفاده کن
- عدد قیمت‌ها را به تومان بنویس
- متن را با پاراگراف‌بندی خوانا بنویس"""


_JSON_OBJ_RE = re.compile(r"\{[^{}]*\"picks\"\s*:\s*\[[^\]]*\][^{}]*\}", re.S)


def _parse_picks(raw_text: str, max_index: int) -> tuple[list[int], str]:
    """Pull `picks` array out of the LLM response.

    Returns (valid_indices_zero_based, narrative_text). If parsing fails the
    indices list is empty and the entire response is treated as narrative.
    """
    if not raw_text:
        return [], ""

    match = _JSON_OBJ_RE.search(raw_text)
    if not match:
        return [], raw_text.strip()

    try:
        obj = json.loads(match.group(0))
    except (ValueError, TypeError):
        return [], raw_text.strip()

    raw_picks = obj.get("picks") or []
    indices: list[int] = []
    seen: set[int] = set()
    for v in raw_picks:
        try:
            i = int(v)
        except (TypeError, ValueError):
            continue
        if 1 <= i <= max_index and i not in seen:
            indices.append(i - 1)
            seen.add(i)
        if len(indices) >= _PRODUCT_PICK_LIMIT:
            break

    narrative = (raw_text[: match.start()] + raw_text[match.end():]).strip()
    return indices, narrative


def _annotate_matching_variant(product: dict, size: str) -> None:
    """Add `matched_variant` to a product dict if a variant matches the size."""
    variants = product.get("variants") or []
    for v in variants:
        attrs = v.get("attributes") or {}
        for group_name, attr_val in attrs.items():
            # Match size attribute group (Persian "اندازه" or English "size")
            if "اندازه" in group_name.lower() or "size" in group_name.lower():
                if attr_val.upper() == size.upper() and v.get("in_stock"):
                    product["matched_variant"] = v
                    product["matched_size"] = attr_val
                    return
    # No exact match found — leave without annotation


def _build_fallback_text(answers: dict, calculated_size: str = "") -> str:
    """Build a meaningful fallback recommendation text when LLM is unavailable."""
    category = answers.get("category", "")
    is_fabric = category.lower() in ("fabric", "پارچه")

    # Support both multi-product and legacy formats
    garment_types = answers.get("garmentTypes") or answers.get("fabricTypes") or []
    subcategory = answers.get("garmentType") or answers.get("fabricType") or ""

    parts = ["سلام! بر اساس اطلاعاتی که از شما دریافت کردیم، محصولات زیر را برای شما انتخاب کرده‌ایم."]

    if calculated_size:
        parts.append(f"سایز پیشنهادی برای شما: {calculated_size}.")

    if garment_types:
        parts.append(f"محصولات برای دسته‌بندی‌های «{'» و «'.join(garment_types)}» فیلتر شده‌اند.")
    elif subcategory:
        parts.append(f"محصولات از دسته‌بندی «{subcategory}» برای شما فیلتر شده‌اند.")

    # Aggregate preferences from all product types for the fallback text
    product_answers_map = answers.get("productAnswers") or {}
    all_styles, all_occasions, all_seasons = set(), set(), set()
    for _slug, pa in product_answers_map.items():
        for v in (pa.get("style") if isinstance(pa.get("style"), list) else [pa.get("style")] if pa.get("style") else []):
            all_styles.add(str(v))
        for v in (pa.get("occasion") if isinstance(pa.get("occasion"), list) else [pa.get("occasion")] if pa.get("occasion") else []):
            all_occasions.add(str(v))
        for v in (pa.get("season") if isinstance(pa.get("season"), list) else [pa.get("season")] if pa.get("season") else []):
            all_seasons.add(str(v))

    # Fall back to flat answers if no productAnswers
    if not product_answers_map:
        style = answers.get("style", "")
        if isinstance(style, list):
            all_styles = set(str(s) for s in style)
        elif style:
            all_styles = {str(style)}
        occasion = answers.get("occasion", "")
        if isinstance(occasion, list):
            all_occasions = set(str(o) for o in occasion)
        elif occasion:
            all_occasions = {str(occasion)}
        season = answers.get("season", "")
        if isinstance(season, list):
            all_seasons = set(str(s) for s in season)
        elif season:
            all_seasons = {str(season)}

    details = []
    if all_styles:
        details.append(f"استایل {'، '.join(all_styles)}")
    if all_occasions:
        details.append(f"مناسب {'، '.join(all_occasions)}")
    if all_seasons:
        details.append(f"مناسب فصل {'، '.join(all_seasons)}")
    if details:
        parts.append("این محصولات با توجه به " + " و ".join(details) + " انتخاب شده‌اند.")

    if is_fabric:
        colors = answers.get("colors", "")
        if isinstance(colors, list):
            colors = "، ".join(str(c) for c in colors)
        if colors:
            parts.append(f"رنگ‌های مورد نظر شما ({colors}) در انتخاب لحاظ شده است.")

    parts.append("برای مشاوره دقیق‌تر و شخصی‌سازی بیشتر، از بخش چت با مشاور استفاده کنید.")

    return " ".join(parts)


async def _fetch_products_multi_or_single(
    answers: dict, gender: str, calculated_size: str,
) -> tuple[list[dict], str]:
    """Fetch products supporting both multi-product and legacy single-product formats.

    Multi-product format (new):
        answers = {
            "category": "garment",
            "garmentTypes": ["shirt", "shorts"],
            "productAnswers": {"shirt": {...}, "shorts": {...}}
        }

    Legacy format:
        answers = {"category": "garment", "garmentType": "shirt", "size": "M", ...}
    """
    garment_types = answers.get("garmentTypes") or answers.get("fabricTypes") or []
    product_answers_map = answers.get("productAnswers") or {}

    if garment_types and product_answers_map:
        # Multi-product mode
        category = answers.get("category", "")
        is_fabric = category.lower() in ("fabric", "پارچه")
        all_products: list[dict] = []
        product_source = "shop"
        seen_ids: set = set()
        cms_failed = False  # track if CMS is unreachable

        for ptype_slug in garment_types:
            type_answers: dict = dict(product_answers_map.get(ptype_slug, {}))
            # Inject category + subcategory so the product service can filter
            type_answers["category"] = category
            if is_fabric:
                type_answers["fabricType"] = ptype_slug
            else:
                type_answers["garmentType"] = ptype_slug

            type_size = type_answers.get("size") or calculated_size

            # If CMS already failed for a previous type, skip to avoid serial timeouts
            if cms_failed:
                logger.warning(
                    "Skipping CMS fetch for type '%s' — CMS already unreachable",
                    ptype_slug,
                )
                product_source = "mock"
                continue

            products, src = (
                await product_service.fetch_products_for_recommendation_with_source(
                    type_answers, gender=gender, calculated_size=type_size,
                )
            )
            if src == "mock":
                product_source = "mock"
                # Check if we got mock data because CMS failed (not just empty results)
                # If the products are the default mocks, CMS is likely unreachable
                if not all_products:
                    cms_failed = True

            # Tag each product with its requested type and limit per type
            count = 0
            for p in products:
                pid = p.get("id")
                if pid and pid in seen_ids:
                    continue
                if pid:
                    seen_ids.add(pid)
                p["_requested_type"] = ptype_slug
                all_products.append(p)
                count += 1
                if count >= _MAX_PRODUCTS_PER_TYPE:
                    break

        return all_products, product_source

    # Legacy single-product mode
    return await product_service.fetch_products_for_recommendation_with_source(
        answers, gender=gender, calculated_size=calculated_size,
    )


@router.post("")
async def get_recommendations(
    body: RecommendationRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Generate personalised product recommendations.

    Body: { "upload_id": "..." }  — uses latest upload if omitted.
    """
    try:
        upload_id = body.upload_id

        # Resolve upload
        if not upload_id:
            uploads = _list_user_metadata(current_user["id"])
            if not uploads:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No uploads found for this user",
                )
            upload_id = uploads[0]["id"]

        upload = _load_metadata(upload_id)
        if not upload or str(upload.get("user_id")) != str(current_user["id"]):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Upload not found",
            )

        measurements = _extract_average_measurements(upload)
        questionnaire = upload.get("questionnaire", {})
        answers = questionnaire.get("answers", {})

        # Determine gender and body model from upload metadata
        gender = upload.get("gender", "male") or "male"
        pr = upload.get("processing_results") or {}
        if isinstance(pr, str):
            try:
                pr = json.loads(pr)
            except (json.JSONDecodeError, TypeError):
                pr = {}
        body_model = pr.get("body_model", "adult") or "adult"

        # Calculate clothing size from measurements
        calculated_size_info = {}
        try:
            from app.services.size_calculator import calculate_size
            calculated_size_info = calculate_size(
                measurements, gender=gender, body_model=body_model,
            )
        except Exception as e:
            logger.warning("Size calculation failed: %s", e)

        calculated_size = calculated_size_info.get("size") or ""

        # Quick CMS reachability check — avoid serial 30s timeouts per product type
        cms_ok = await product_service.check_cms_reachable()
        if not cms_ok:
            logger.warning("CMS unreachable at %s — using mock products", product_service.api_base_url)

        # Fetch products — multi-product or legacy single-product mode
        if cms_ok:
            products, product_source = await _fetch_products_multi_or_single(
                answers, gender, calculated_size,
            )
        else:
            products = product_service._get_mock_products()
            product_source = "mock"

        # Scale limits for multi-product mode
        garment_types = answers.get("garmentTypes") or answers.get("fabricTypes") or []
        num_types = max(len(garment_types), 1)
        effective_max_in_prompt = min(len(products), _MAX_PRODUCTS_IN_PROMPT * num_types)
        effective_pick_limit = min(
            _PICK_LIMIT_PER_TYPE * num_types if num_types > 1 else _PRODUCT_PICK_LIMIT,
            effective_max_in_prompt,
        )

        prompt_products = products[:effective_max_in_prompt]

        # Build LLM prompt and generate
        raw_response = ""
        try:
            from app.services.llm import llm_manager

            if llm_manager.is_ready:
                prompt = _build_prompt(
                    measurements, answers, prompt_products, calculated_size,
                    pick_limit=effective_pick_limit,
                )
                # Scale tokens for multi-product (more types → more commentary needed)
                max_tokens = 2048 + (512 * max(num_types - 1, 0))
                response = llm_manager.generate(
                    prompt=prompt,
                    max_new_tokens=min(max_tokens, 4096),
                    temperature=0.7,
                )
                raw_response = response.text or ""
        except Exception as e:
            logger.error("LLM recommendation generation failed: %s", e)

        pick_indices, narrative = _parse_picks(raw_response, len(prompt_products))

        if pick_indices:
            recommended_products = [prompt_products[i] for i in pick_indices]
        else:
            recommended_products = prompt_products[:effective_pick_limit]
            narrative = raw_response.strip() or narrative

        recommendations_text = narrative or _build_fallback_text(answers, calculated_size)

        recommended_ids = [
            str(p.get("id")) for p in recommended_products if p.get("id") is not None
        ]

        # Annotate each product with best matching variant for the user's size
        for p in recommended_products:
            if calculated_size:
                _annotate_matching_variant(p, calculated_size)
            # Clean internal metadata before sending to frontend
            p.pop("_requested_type", None)

        return {
            "upload_id": upload_id,
            "recommendations_text": recommendations_text,
            "products": recommended_products,
            "recommended_ids": recommended_ids,
            "questionnaire_summary": answers,
            "product_source": product_source,  # "shop" | "mock"
            "llm_grounded": bool(pick_indices),
            "calculated_size": calculated_size_info,
            "gender": gender,
            "body_model": body_model,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Recommendations endpoint error:\n%s", traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {str(e)}",
        )


@router.post("/size-recommendation")
async def size_recommendation(
    body: SizeRecommendationRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Given an upload_id and a list of available sizes, return the best-matching
    size based on the user's body measurements.
    """
    try:
        upload = _load_metadata(body.upload_id)
        if not upload or str(upload.get("user_id")) != str(current_user["id"]):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Upload not found",
            )

        measurements = _extract_average_measurements(upload)
        gender = upload.get("gender", "male") or "male"
        pr = upload.get("processing_results") or {}
        if isinstance(pr, str):
            try:
                pr = json.loads(pr)
            except (json.JSONDecodeError, TypeError):
                pr = {}
        body_model = pr.get("body_model", "adult") or "adult"

        from app.services.size_calculator import recommend_from_available

        result = recommend_from_available(
            measurements,
            body.available_sizes,
            gender=gender,
            body_model=body_model,
        )
        result["gender"] = gender
        result["body_model"] = body_model
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Size recommendation error:\n%s", traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {str(e)}",
        )
