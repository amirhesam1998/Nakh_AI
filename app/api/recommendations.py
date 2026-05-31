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


def _format_products_for_prompt(products: list[dict]) -> str:
    """Render up to N products as a numbered list. Indices are 1-based."""
    lines = []
    for idx, p in enumerate(products[:_MAX_PRODUCTS_IN_PROMPT], start=1):
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
        lines.append(
            f"{idx}. {title} | قیمت: {price_str} تومان | "
            f"دسته: {category} | برند: {brand} | مشخصات: {specs_str}"
        )
    return "\n".join(lines)


def _build_prompt(
    measurements: dict,
    answers: dict,
    products: list[dict],
    calculated_size: str = "",
) -> str:
    """Build a Persian prompt for the LLM that asks for a JSON pick list."""
    meas_text = "\n".join(
        f"- {_safe(k, 40)}: {_safe(v, 40)}" for k, v in measurements.items() if v
    ) or "-"
    answers_text = "\n".join(
        f"- {_safe(k, 40)}: {_safe(v)}" for k, v in answers.items()
    ) or "-"
    products_text = _format_products_for_prompt(products)
    n = min(len(products), _MAX_PRODUCTS_IN_PROMPT)

    size_line = f"\nسایز محاسبه‌شده: {calculated_size}" if calculated_size else ""

    # Extract key preference fields for emphasis
    style_val = answers.get("style", "-")
    if isinstance(style_val, list):
        style_val = "، ".join(str(s) for s in style_val)
    occasion_val = _safe(answers.get("occasion", "-"))
    season_val = _safe(answers.get("season", "-"))

    prefs_block = ""
    if style_val and style_val != "-":
        prefs_block += f"\nاستایل ترجیحی: {_safe(style_val)}"
    if occasion_val and occasion_val != "-":
        prefs_block += f"\nمناسبت: {occasion_val}"
    if season_val and season_val != "-":
        prefs_block += f"\nفصل: {season_val}"

    return f"""تو یک مشاور لباس حرفه‌ای هستی. بر اساس اندازه‌های بدن، سایز محاسبه‌شده، ترجیحات کاربر و لیست محصولات شماره‌گذاری‌شده زیر، بهترین محصولات را انتخاب کن. محصولاتی را انتخاب کن که سایز، استایل، مناسبت و فصل آن‌ها با نیاز کاربر مطابقت دارد.

اندازه‌های بدن:
{meas_text}{size_line}{prefs_block}

ترجیحات کاربر (پاسخ پرسشنامه):
{answers_text}

محصولات موجود (هر محصول یک شماره دارد، فقط از همین شماره‌ها استفاده کن):
{products_text}

پاسخ خود را دقیقاً به این فرمت بده:
خط اول: یک شیء JSON به شکل {{"picks": [شماره‌ها]}} که حداکثر {_PRODUCT_PICK_LIMIT} شماره از ۱ تا {n} انتخاب می‌کند.
بعد از آن: توضیح فارسی برای هر انتخاب در یک پاراگراف کوتاه."""


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

        # Fetch products filtered by questionnaire answers + size + gender
        products, product_source = (
            await product_service.fetch_products_for_recommendation_with_source(
                answers, gender=gender, calculated_size=calculated_size,
            )
        )
        prompt_products = products[:_MAX_PRODUCTS_IN_PROMPT]

        # Build LLM prompt and generate
        raw_response = ""
        try:
            from app.services.llm import llm_manager

            if llm_manager.is_ready:
                prompt = _build_prompt(measurements, answers, prompt_products, calculated_size)
                response = llm_manager.generate(
                    prompt=prompt,
                    max_new_tokens=1024,
                    temperature=0.7,
                )
                raw_response = response.text or ""
        except Exception as e:
            logger.error("LLM recommendation generation failed: %s", e)

        pick_indices, narrative = _parse_picks(raw_response, len(prompt_products))

        if pick_indices:
            recommended_products = [prompt_products[i] for i in pick_indices]
        else:
            # LLM didn't ground its picks — surface the top of the catalog and
            # use the entire response (if any) as commentary.
            recommended_products = prompt_products[:_PRODUCT_PICK_LIMIT]
            narrative = raw_response.strip() or narrative

        recommendations_text = narrative or (
            "بر اساس اندازه‌ها و ترجیحات شما، محصولات زیر پیشنهاد می‌شوند. "
            "برای مشاوره دقیق‌تر، لطفاً از بخش چت استفاده کنید."
        )

        recommended_ids = [
            str(p.get("id")) for p in recommended_products if p.get("id") is not None
        ]

        # Annotate each product with best matching variant for the user's size
        if calculated_size:
            for p in recommended_products:
                _annotate_matching_variant(p, calculated_size)

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
