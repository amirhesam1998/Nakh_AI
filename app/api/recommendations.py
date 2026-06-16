"""
Product recommendation endpoint.

Combines body measurements + questionnaire answers + product catalog
and asks the LLM for personalized recommendations in Persian.
"""
import asyncio
import json
import logging
import re
import traceback
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool
from pydantic import BaseModel

from app.config import settings
from app.core.dependencies import get_current_active_user
from app.services.product_service import product_service
from app.services import upload_store, events
from app.services.metrics import metrics
from app.services.concurrency import llm_slot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# Cap how much of any single user-supplied value we ever interpolate into a
# prompt — protects against runaway tokens and pads against trivial injection.
_MAX_FIELD_LEN = 200
_MAX_PRODUCTS_IN_PROMPT = 10
_PRODUCT_PICK_LIMIT = 5
_MAX_PRODUCTS_PER_TYPE = 8   # per-type fetch limit in multi-product mode
_PICK_LIMIT_PER_TYPE = 3     # LLM picks per product type in multi-product mode


# ── Static domain knowledge ──
# These blocks never change between requests. Holding them as module constants
# (instead of rebuilding the f-string every call) and sending them as a STABLE
# system prompt lets Ollama reuse its cached prompt prefix → lower latency and
# token cost on every recommendation.

_FABRIC_KNOWLEDGE = """
--- دانش تخصصی تو به عنوان مشاور پارچه ---

تو این اطلاعات را از سال‌ها تجربه داری و باید در مشاوره‌ات از آنها استفاده کنی:

پارچه و فصل:
- بهار/تابستان: کتان (لینن) نفس می‌کشد و خنک نگه می‌دارد. پنبه سبک ایده‌آل است. ویسکوز و ریون افتادگی خوب و خنکی دارند.
- پاییز/زمستان: پشم گرم نگه می‌دارد و فرم خوبی دارد. کشمیر لوکس و سبک است. فِلانل (پنبه یا پشم بافت‌دار) برای لایه‌های میانی عالی است.
- چهار فصل: گاباردین، کرپ، و پنبه‌های با وزن متوسط.

پارچه و کاربرد:
- رسمی/اداری: پشم سوپر ۱۲۰ یا بالاتر، ساتن، تافته. بافت ریز و صاف نشان‌دهنده کیفیت است.
- کژوال: جین، شامبری، پنبه آکسفورد. بافت‌های درشت‌تر و طبیعی‌تر.
- مجلسی: ابریشم، ساتن، حریر، دانتل. درخشندگی و افتادگی مهم است.
- ورزشی: پلی‌استر، نایلون، الاستان. کش‌پذیری و دفع رطوبت.

نکات مهم پارچه:
- وزن پارچه (گرم بر متر مربع) تعیین‌کننده فصل و کاربرد است
- پارچه‌های طبیعی (پنبه، کتان، پشم، ابریشم) تنفس بهتری دارند ولی چروک بیشتری می‌خورند
- پارچه‌های مصنوعی (پلی‌استر) چروک نمی‌خورند ولی در گرما ناراحت‌کننده‌اند
- ترکیبی (مثلاً ۸۰٪ پنبه ۲۰٪ پلی‌استر) مزایای هر دو را دارد"""

_STYLIST_KNOWLEDGE = """
--- دانش تخصصی تو به عنوان استایلیست ---

تو این اطلاعات را از سال‌ها تجربه داری و باید در مشاوره‌ات از آنها استفاده کنی:

فصل و انتخاب لباس:
- زمستان: لایه‌پوشی کلید است. یک لایه پایه (تی‌شرت یا پیراهن نخی)، لایه میانی (ژاکت یا بلیزر پشمی)، و لایه بیرونی (کت یا پالتو). پارچه‌های ضخیم‌تر مثل پشم، کشمیر و فلانل. رنگ‌های تیره و زمینی (سرمه‌ای، زغالی، بُردو، خاکی).
- تابستان: پارچه‌های سبک و تنفس‌پذیر — کتان، پنبه نازک. رنگ‌های روشن و خنک (سفید، آبی آسمانی، بژ). آستین کوتاه، یقه باز. از پلی‌استر ضخیم اجتناب کنید.
- بهار/پاییز: لایه‌های سبک — ژاکت نازک، بلیزر، هودی. رنگ‌های ملایم. شلوارهای چینو و جین مناسب‌ترند.

استایل و شخصیت:
- کلاسیک: خطوط تمیز، رنگ‌های ثابت (سرمه‌ای، خاکستری، سفید)، الگوهای ساده (راه‌راه نازک، شطرنجی ریز). کت تک‌دکمه، پیراهن یقه ایتالیایی، شلوار پارچه‌ای. بی‌زمان و همیشه شیک.
- کژوال: راحتی اولویت دارد ولی نه شلخته. جین خوش‌فرم، تی‌شرت با کیفیت، کفش کتانی تمیز. لایه‌پوشی با ژاکت یا کاپشن سبک.
- رسمی: کت و شلوار ست، پیراهن رنگ روشن، کراوات. فیت بدن مهم‌ترین عامل است — نه خیلی تنگ، نه خیلی گشاد. طول آستین کت باید ۱-۲ سانت از آستین پیراهن کوتاه‌تر باشد.
- اسپرت/ورزشی: پارچه‌های انعطاف‌پذیر، فیت آزاد ولی نه بی‌فرم. رنگ‌های زنده و ترکیبی.

مناسبت و لباس:
- محل کار/اداری: حرفه‌ای ولی نه سخت. شلوار پارچه‌ای + پیراهن + بلیزر. رنگ‌های خنثی. از رنگ‌های خیلی زنده و طرح‌های شلوغ اجتناب کنید.
- مهمانی/عروسی: کت و شلوار رسمی (زنانه: لباس مجلسی یا کت‌دامن). رنگ‌های غنی و پارچه‌های با کیفیت.
- روزمره/خیابانی: ترکیب راحتی و استایل. اسنیکر + جین + تی‌شرت گرافیکی. بازی با اکسسوری.
- سفر: لباس‌های چندکاره که چروک نخورند. رنگ‌هایی که با هم ست شوند تا با کمترین لباس بیشترین ترکیب را داشته باشید.

فیت و اندام:
- شلوار: فاق شلوار باید با اندام مطابقت داشته باشد. فاق بلند → پاها بلندتر. برای اندام‌های کوتاه‌تر، شلوارهای slim و straight بهترند.
- پیراهن: درز شانه باید دقیقاً روی نوک شانه بنشیند. نه روی بازو و نه روی گردن.
- کت: وقتی دکمه بسته است نباید X شکل بیفتد (یعنی تنگ است). باید بدون کشش صاف بنشیند.
- یقه: یقه گرد برای صورت‌های کشیده. یقه V برای صورت‌های گرد و گردن‌های کوتاه. یقه V بصری گردن را بلندتر می‌کند.

هماهنگی رنگ:
- قانون ۳ رنگ: حداکثر ۳ رنگ اصلی در یک تیپ. یک رنگ غالب، یک رنگ مکمل، یک رنگ تأکیدی.
- ترکیب‌های امن: سرمه‌ای + سفید + قهوه‌ای. خاکستری + مشکی + سفید. بژ + آبی + سفید.
- رنگ‌های پوست: پوست روشن → رنگ‌های سرد (آبی، بنفش، سبز). پوست گندمی → رنگ‌های گرم (خاکی، زیتونی، آجری)."""


def _build_system_prompt(is_fabric: bool) -> str:
    """Stable system message: role + domain knowledge (cacheable by Ollama)."""
    role_desc = "مشاور پارچه و منسوجات" if is_fabric else "مشاور لباس و استایلیست شخصی"
    knowledge = _FABRIC_KNOWLEDGE if is_fabric else _STYLIST_KNOWLEDGE
    return (
        f"تو یک {role_desc} حرفه‌ای و باتجربه هستی. تو فقط محصول نمی‌فروشی — "
        f"تو به مشتری کمک می‌کنی بهترین نسخه خودش باشد. مشتری به تو اعتماد کرده و "
        f"تو مثل یک دوست متخصص با او صحبت می‌کنی.\n{knowledge}"
    )


class RecommendationRequest(BaseModel):
    upload_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    """Behavioural feedback from the storefront — seeds the data flywheel."""
    event_type: str               # product_clicked | added_to_cart | purchased | size_feedback | fit_feedback
    product_id: Optional[str] = None
    upload_id: Optional[str] = None
    recommended_size: Optional[str] = None
    chosen_size: Optional[str] = None
    fit: Optional[str] = None     # "too_tight" | "perfect" | "too_loose"
    extra: dict = {}


def _sse(event: str, data: Any) -> str:
    """Format a Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


class SizeRecommendationRequest(BaseModel):
    upload_id: str
    available_sizes: list[str] = []


METADATA_DIR = settings.media_path / "metadata"


def _load_metadata(upload_id: str) -> Optional[dict]:
    # Indexed store — no full-directory scan.
    return upload_store.load_metadata(upload_id)


def _list_user_metadata(user_id: str) -> list[dict]:
    return upload_store.list_user_metadata(user_id)


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


def _interpret_body_shape(measurements: dict, gender: str) -> str:
    """Derive body shape insights from raw measurements for the LLM."""
    lines: list[str] = []

    chest = measurements.get("chest_circum_cm") or measurements.get("chest")
    waist = measurements.get("waist_circum_cm") or measurements.get("waist")
    hips = measurements.get("hip_circum_cm") or measurements.get("hips")
    shoulder = measurements.get("shoulder_width_cm") or measurements.get("shoulder_width")
    height = measurements.get("height_cm") or measurements.get("height")
    bmi = measurements.get("bmi")

    if chest and waist and hips:
        chest_v, waist_v, hips_v = float(chest), float(waist), float(hips)
        if gender == "female":
            if hips_v > chest_v * 1.05:
                lines.append("فرم بدن: گلابی‌شکل (باسن پهن‌تر از سینه) — لباس‌هایی با بالاتنه فیت و دامن/شلوار A-line مناسب‌ترند. رنگ‌های تیره پایین‌تنه و رنگ‌های روشن بالاتنه تعادل ایجاد می‌کنند.")
            elif abs(chest_v - hips_v) < 5 and waist_v < chest_v * 0.8:
                lines.append("فرم بدن: ساعت شنی — کمر باریک با تناسب سینه و باسن. لباس‌های فیت و کمردار عالی هستند. از فرم طبیعی بدن استفاده کنید.")
            elif abs(chest_v - hips_v) < 5 and waist_v >= chest_v * 0.8:
                lines.append("فرم بدن: مستطیلی — اندام متناسب. لباس‌هایی که کمر را تعریف می‌کنند (کمربند، برش‌های امپایر) توصیه می‌شود.")
            elif chest_v > hips_v * 1.05:
                lines.append("فرم بدن: مثلث معکوس — شانه و سینه پهن‌تر. شلوارهای پاچه‌گشاد و دامن‌های کلوش تعادل ایجاد می‌کنند.")
        else:
            if shoulder and float(shoulder) > 45:
                if waist_v < chest_v * 0.85:
                    lines.append("فرم بدن: V شکل/ورزشکاری — شانه‌های پهن و کمر باریک. پیراهن‌های فیت و اسلیم‌فیت عالی هستند. از لباس‌های خیلی گشاد اجتناب کنید.")
                else:
                    lines.append("فرم بدن: مستطیلی/استاندارد — اندام متعادل. اکثر فرم‌های لباس مناسب هستند. فیت رگولار بهترین انتخاب است.")
            elif waist_v > chest_v * 0.95:
                lines.append("فرم بدن: بیضی — ناحیه شکم بزرگ‌تر. لباس‌های استراکچر با خطوط عمودی، رنگ‌های تیره و جنس‌های سفت‌تر (نه چسبان) مناسب‌ترند.")

    if bmi:
        bmi_v = float(bmi)
        if bmi_v < 18.5:
            lines.append("اندام لاغر — لایه‌پوشی (لایه‌رینگ) و پارچه‌های ضخیم‌تر حجم بصری ایجاد می‌کنند. طرح‌های افقی و رنگ‌های روشن مفیدند.")
        elif bmi_v > 30:
            lines.append("ساختار درشت — پارچه‌های ساختاردار (نه نرم و افتادنی) فرم بهتری می‌دهند. خطوط عمودی، یقه‌های V و رنگ‌های تیره لاغرتر نشان می‌دهند.")

    if height:
        h = float(height)
        if h < 165:
            lines.append("قد کوتاه‌تر از میانگین — شلوارهای فاق بلند پاها را بلندتر نشان می‌دهند. از لباس‌های خیلی بلند و شلوارهای پاچه‌گشاد اجتناب کنید. رنگ یکدست از سر تا پا قد را بلندتر نشان می‌دهد.")
        elif h > 185:
            lines.append("قد بلند — آزادی عمل بیشتری در انتخاب لباس دارید. لایه‌پوشی و شلوارهای پاچه‌گشاد عالی به نظر می‌رسند. شلوار با برک مناسب انتخاب کنید.")

    return "\n".join(lines) if lines else ""


def _build_prompt(
    measurements: dict,
    answers: dict,
    products: list[dict],
    calculated_size: str = "",
    pick_limit: int = _PRODUCT_PICK_LIMIT,
) -> tuple[str, str]:
    """Build the (system_prompt, user_prompt) pair for the recommendation LLM.

    The system prompt is the stable role + domain-knowledge block (cached by
    Ollama across requests); the user prompt carries the per-request profile,
    catalogue and output instructions.
    """
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

    # ── Body shape analysis ──
    gender = answers.get("gender", answers.get("_audience", "male"))
    if isinstance(gender, str) and gender in ("مردانه", "male", "men"):
        gender_key = "male"
    else:
        gender_key = "female"
    body_analysis = _interpret_body_shape(measurements, gender_key)
    body_section = f"\n\nتحلیل فرم بدن:\n{body_analysis}" if body_analysis else ""

    # ── Multi-product instruction addition ──
    multi_instruction = ""
    if is_multi:
        types_str = "، ".join(f"«{t}»" for t in garment_types)
        multi_instruction = f"""
نکته مهم: مشتری به دنبال چند نوع محصول مختلف است: {types_str}
تلاش کن برای هر نوع محصول درخواستی حداقل یک پیشنهاد از لیست داشته باشی.
محصولات را با هم ست کن و توضیح بده چگونه با هم ترکیب می‌شوند."""

    # System prompt = stable role + domain knowledge (cacheable by Ollama).
    system_prompt = _build_system_prompt(is_fabric)

    user_prompt = f"""{multi_instruction}
--- پروفایل مشتری ---

اندازه‌های بدن:
{meas_text}{size_line}{body_section}

ترجیحات و سلیقه:{prefs_block}

پاسخ‌های پرسشنامه:
{answers_text}

--- موجودی فروشگاه ---
{products_text}

--- دستورالعمل خروجی ---

خط اول: یک شیء JSON به شکل {{"picks": [شماره‌ها]}} — حداکثر {pick_limit} شماره از ۱ تا {n}.

سپس یک متن مشاوره فارسی بنویس. تو داری با مشتری حرف می‌زنی — نه گزارش می‌نویسی. مثل یک استایلیست واقعی که کنار مشتری ایستاده:

۱. شروع گرم:
یک جمله صمیمی خوشامدگویی. به یکی از ویژگی‌های مشتری اشاره کن (مثلاً «با اندام ورزشکاری مثل شما...» یا «با توجه به سلیقه کلاسیک‌تون...»).

۲. توضیح چرایی هر انتخاب (مهم‌ترین بخش):
برای هر محصول، نگو فقط «این محصول مناسب شماست». بگو *چرا*:
- اگر مشتری فصل زمستان انتخاب کرده، توضیح بده چرا جنس این پارچه در سرما عملکرد خوبی دارد، چرا لایه‌پوشی با این محصول راحت است
- اگر استایل کلاسیک خواسته، بگو چه ویژگی‌هایی این محصول را کلاسیک می‌کند (خطوط تمیز، رنگ خنثی، بافت صاف)
- اگر مناسبت رسمی است، توضیح بده چرا این فیت و پارچه برای محیط کاری یا مراسم مناسب است
- از اندازه‌های بدن استفاده کن — مثلاً «با عرض شانه ۴۵ سانت‌تون، این پیراهن اسلیم‌فیت خیلی خوب می‌شینه» یا «با دور کمر شما، فاق بلند این شلوار تناسب بهتری ایجاد می‌کنه»
- اگر سایز محاسبه شده، بگو کدام سایز/واریانت محصول مناسب‌تر است

۳. ترکیب و ست‌سازی:
یک تیپ کامل پیشنهاد بده. محصولات انتخابی را کنار هم بگذار و توضیح بده چطور یک لوک کامل می‌سازند. مثلاً: «این پیراهن آبی رو با شلوار خاکستری ست کنید — کنتراست رنگی ملایمی ایجاد می‌کنه که هم برای جلسه کاری و هم شام دوستانه مناسبه.»

۴. نکات تکمیلی (اکسسوری، نگهداری، یا هر نکته مفید):
- اکسسوری‌های مکمل: کمربند، کفش، ساعت — حتی اگر در فروشگاه نیست
- اگر پارچه حساس است (مثلاً ابریشم یا کشمیر): یک نکته کوتاه نگهداری
- نکته‌ای که مشتری نمی‌دانست و مفید است (مثلاً «کتان بعد از چند بار شستشو نرم‌تر و راحت‌تر می‌شه»)

۵. جمع‌بندی دلگرم‌کننده:
یک جمله پایانی که مشتری احساس کند انتخاب خوبی خواهد داشت.

قوانین نوشتار:
- کل متن فارسی باشد
- لحن: مثل یک دوست متخصص، نه یک ربات. صمیمی ولی حرفه‌ای.
- هرگز جواب پرسشنامه را تکرار نکن (نگو «شما فصل زمستان انتخاب کردید پس...»). به جای آن دانش خودت را نشان بده (بگو «در هوای سرد، پارچه پشمی این کت...»).
- از نام واقعی محصولات و برندها و مشخصات از لیست فروشگاه استفاده کن
- قیمت‌ها را به تومان با جداکننده هزارگان بنویس
- متن را خوانا پاراگراف‌بندی کن"""

    return system_prompt, user_prompt


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

    parts = ["سلام! خوشحالیم که برای انتخاب بهترین محصول به ما مراجعه کردید."]

    if calculated_size:
        parts.append(f"بر اساس اندازه‌گیری بدن شما، سایز {calculated_size} برای شما مناسب‌ترین انتخاب است.")

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

    # Build conversational advice based on preferences
    if all_seasons:
        season_str = "، ".join(all_seasons)
        season_tips = {
            "زمستان": "برای فصل سرد، پارچه‌های ضخیم‌تر و لایه‌پوشی بهترین انتخاب هستند.",
            "تابستان": "در هوای گرم، پارچه‌های سبک و تنفس‌پذیر مثل کتان و پنبه نازک راحت‌ترین گزینه‌اند.",
            "بهار": "در بهار، لایه‌های سبک و رنگ‌های ملایم حس تازگی می‌دهند.",
            "پاییز": "برای پاییز، رنگ‌های گرم و زمینی با ژاکت یا بلیزر سبک ایده‌آل هستند.",
        }
        for s, tip in season_tips.items():
            if s in season_str:
                parts.append(tip)
                break
        else:
            parts.append(f"محصولات مناسب فصل {season_str} برای شما انتخاب شده‌اند.")

    if all_styles:
        style_str = "، ".join(all_styles)
        parts.append(f"با توجه به سبک {style_str} مورد علاقه شما، محصولاتی انتخاب شده‌اند که هم شیک و هم کاربردی باشند.")

    if all_occasions:
        occ_str = "، ".join(all_occasions)
        parts.append(f"این محصولات مناسب {occ_str} هستند و می‌توانید با اطمینان در این موقعیت‌ها از آنها استفاده کنید.")

    if is_fabric:
        colors = answers.get("colors", "")
        if isinstance(colors, list):
            colors = "، ".join(str(c) for c in colors)
        if colors:
            parts.append(f"پارچه‌ها در رنگ‌های {colors} که انتخاب کردید موجود هستند.")

    if garment_types:
        types_str = "» و «".join(garment_types)
        parts.append(f"محصولات از دسته‌بندی‌های «{types_str}» برای شما گلچین شده‌اند. سعی کنید رنگ‌هایی انتخاب کنید که با هم ست شوند تا یک تیپ هماهنگ داشته باشید.")

    parts.append("\nبرای مشاوره تخصصی‌تر و کمک در انتخاب ست کامل، از بخش چت با مشاور استفاده کنید. مشاور ما می‌تواند بر اساس اندام شما بهترین فیت و ترکیب رنگ را پیشنهاد دهد.")

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
                continue

            products, src = (
                await product_service.fetch_products_for_recommendation_with_source(
                    type_answers, gender=gender, calculated_size=type_size,
                )
            )
            # "shop" is success; "mock"/"unavailable" mean the catalogue failed.
            # Only downgrade the overall source when we have NO real products —
            # a later failure shouldn't override products already gathered.
            if src != "shop" and not all_products:
                product_source = src
                cms_failed = True  # stop hammering CMS for remaining types

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


def _annotate_product_size(
    product: dict,
    measurements: dict,
    gender: str,
    body_model: str,
    fallback_size: str,
) -> None:
    """Annotate a product with its best size, preferring the product's OWN chart.

    Falls back to the generic calculated size when the product has no chart.
    """
    from app.services.size_calculator import recommend_size_for_product

    try:
        rec = recommend_size_for_product(
            measurements, product, gender=gender, body_model=body_model,
            fallback_size=fallback_size,
        )
        size = rec.get("size")
        if size:
            product["recommended_size_for_product"] = size
            product["size_chart_source"] = rec.get("chart_source", "generic")
            _annotate_matching_variant(product, size)
    except Exception as e:
        logger.debug("Per-product sizing failed: %s", e)
        if fallback_size:
            _annotate_matching_variant(product, fallback_size)


async def _prepare_recommendation(upload_id: Optional[str], user_id: str) -> dict:
    """Resolve upload → measurements → products → prompts.

    Shared by the JSON and streaming endpoints. Raises HTTPException for the
    not-found cases. Returns a context dict.
    """
    # Resolve upload (indexed lookup — no full scan).
    if not upload_id:
        uploads = _list_user_metadata(user_id)
        if not uploads:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No uploads found for this user",
            )
        upload_id = uploads[0]["id"]

    upload = _load_metadata(upload_id)
    if not upload or str(upload.get("user_id")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found",
        )

    measurements = _extract_average_measurements(upload)
    answers = (upload.get("questionnaire", {}) or {}).get("answers", {})

    gender = upload.get("gender", "male") or "male"
    pr = upload.get("processing_results") or {}
    if isinstance(pr, str):
        try:
            pr = json.loads(pr)
        except (json.JSONDecodeError, TypeError):
            pr = {}
    body_model = pr.get("body_model", "adult") or "adult"

    calculated_size_info: dict = {}
    try:
        from app.services.size_calculator import calculate_size
        calculated_size_info = calculate_size(
            measurements, gender=gender, body_model=body_model,
        )
    except Exception as e:
        logger.warning("Size calculation failed: %s", e)
    calculated_size = calculated_size_info.get("size") or ""

    # CMS reachability check — avoids serial timeouts per product type.
    cms_ok = await product_service.check_cms_reachable()
    if cms_ok:
        products, product_source = await _fetch_products_multi_or_single(
            answers, gender, calculated_size,
        )
    else:
        logger.warning("CMS unreachable at %s", product_service.api_base_url)
        products, product_source = product_service._fallback()

    metrics.incr("recommendations.total")
    metrics.incr(f"recommendations.source.{product_source}")

    garment_types = answers.get("garmentTypes") or answers.get("fabricTypes") or []
    num_types = max(len(garment_types), 1)
    effective_max_in_prompt = min(len(products), _MAX_PRODUCTS_IN_PROMPT * num_types)
    effective_pick_limit = min(
        _PICK_LIMIT_PER_TYPE * num_types if num_types > 1 else _PRODUCT_PICK_LIMIT,
        effective_max_in_prompt,
    )
    prompt_products = products[:effective_max_in_prompt]

    system_prompt, user_prompt = _build_prompt(
        measurements, answers, prompt_products, calculated_size,
        pick_limit=effective_pick_limit,
    )
    max_tokens = min(2048 + (512 * max(num_types - 1, 0)), 4096)

    return {
        "upload_id": upload_id,
        "measurements": measurements,
        "answers": answers,
        "gender": gender,
        "body_model": body_model,
        "calculated_size_info": calculated_size_info,
        "calculated_size": calculated_size,
        "product_source": product_source,
        "prompt_products": prompt_products,
        "effective_pick_limit": effective_pick_limit,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "max_tokens": max_tokens,
    }


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
        ctx = await _prepare_recommendation(body.upload_id, current_user["id"])
        prompt_products = ctx["prompt_products"]
        answers = ctx["answers"]
        calculated_size = ctx["calculated_size"]
        product_source = ctx["product_source"]

        # If the catalogue is unavailable in production, surface a clear state
        # rather than fabricated products.
        if product_source == "unavailable" and not prompt_products:
            return {
                "upload_id": ctx["upload_id"],
                "recommendations_text": (
                    "در حال حاضر دسترسی به فروشگاه ممکن نیست. لطفاً کمی بعد دوباره "
                    "تلاش کنید. اندازه‌های شما ذخیره شده‌اند."
                ),
                "products": [],
                "recommended_ids": [],
                "questionnaire_summary": answers,
                "product_source": "unavailable",
                "llm_grounded": False,
                "calculated_size": ctx["calculated_size_info"],
                "gender": ctx["gender"],
                "body_model": ctx["body_model"],
            }

        # LLM generation — bounded by the shared concurrency semaphore and run
        # in a thread (Ollama client is blocking; never block the event loop).
        raw_response = ""
        try:
            from app.services.llm import llm_manager

            if llm_manager.is_ready:
                async with llm_slot("recommendations"):
                    with metrics.timer("recommendations.llm_seconds"):
                        response = await asyncio.to_thread(
                            llm_manager.generate,
                            prompt=ctx["user_prompt"],
                            system_prompt=ctx["system_prompt"],
                            max_new_tokens=ctx["max_tokens"],
                            temperature=0.7,
                        )
                raw_response = response.text or ""
        except Exception as e:
            metrics.incr("recommendations.llm_errors")
            logger.error("LLM recommendation generation failed: %s", e)

        pick_indices, narrative = _parse_picks(raw_response, len(prompt_products))

        if pick_indices:
            recommended_products = [prompt_products[i] for i in pick_indices]
        else:
            recommended_products = prompt_products[: ctx["effective_pick_limit"]]
            narrative = raw_response.strip() or narrative

        recommendations_text = narrative or _build_fallback_text(answers, calculated_size)

        recommended_ids = [
            str(p.get("id")) for p in recommended_products if p.get("id") is not None
        ]

        # Per-product sizing (prefers each product's own size chart) + cleanup.
        for p in recommended_products:
            _annotate_product_size(
                p, ctx["measurements"], ctx["gender"], ctx["body_model"], calculated_size,
            )
            p.pop("_requested_type", None)

        if pick_indices:
            metrics.incr("recommendations.llm_grounded")

        # Behavioural event: which products were shown (seeds ranking/feedback).
        try:
            await events.record_async(
                events.EVENT_RECOMMENDATION_SHOWN,
                user_id=current_user["id"],
                upload_id=ctx["upload_id"],
                product_ids=recommended_ids,
                product_source=product_source,
                llm_grounded=bool(pick_indices),
                calculated_size=calculated_size,
            )
        except Exception:
            pass

        return {
            "upload_id": ctx["upload_id"],
            "recommendations_text": recommendations_text,
            "products": recommended_products,
            "recommended_ids": recommended_ids,
            "questionnaire_summary": answers,
            "product_source": product_source,  # "shop" | "mock" | "unavailable"
            "llm_grounded": bool(pick_indices),
            "calculated_size": ctx["calculated_size_info"],
            "gender": ctx["gender"],
            "body_model": ctx["body_model"],
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


@router.post("/stream")
async def stream_recommendations(
    body: RecommendationRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Streaming variant of POST /recommendations (Server-Sent Events).

    Emits:
      - event: meta   → candidate count, source, calculated size
      - event: token  → narrative text deltas (live typing UX)
      - event: done   → final products, recommended_ids, llm_grounded
      - event: error  → on failure

    This removes the 60–120 s blank wait: the user sees advice as it's written.
    """
    ctx = await _prepare_recommendation(body.upload_id, current_user["id"])
    prompt_products = ctx["prompt_products"]
    answers = ctx["answers"]
    calculated_size = ctx["calculated_size"]
    product_source = ctx["product_source"]

    async def event_gen():
        # Catalogue unavailable → emit a clear terminal state, no fake products.
        if product_source == "unavailable" and not prompt_products:
            yield _sse("meta", {"product_source": "unavailable", "candidates": 0})
            yield _sse("done", {
                "products": [], "recommended_ids": [], "product_source": "unavailable",
                "llm_grounded": False,
                "recommendations_text": (
                    "در حال حاضر دسترسی به فروشگاه ممکن نیست. لطفاً بعداً تلاش کنید."
                ),
                "calculated_size": ctx["calculated_size_info"],
            })
            return

        yield _sse("meta", {
            "product_source": product_source,
            "candidates": len(prompt_products),
            "calculated_size": ctx["calculated_size_info"],
            "gender": ctx["gender"],
        })

        from app.services.llm import llm_manager

        raw_full = ""
        if llm_manager.is_ready and llm_manager.supports_streaming:
            picks_hidden = False
            try:
                async with llm_slot("recommendations"):
                    with metrics.timer("recommendations.llm_seconds"):
                        sync_gen = llm_manager.generate_stream(
                            prompt=ctx["user_prompt"],
                            system_prompt=ctx["system_prompt"],
                            max_new_tokens=ctx["max_tokens"],
                            temperature=0.7,
                        )
                        async for delta in iterate_in_threadpool(sync_gen):
                            raw_full += delta
                            if not picks_hidden:
                                # Hold back the leading {"picks": [...]} line so
                                # the user sees prose, not JSON.
                                m = _JSON_OBJ_RE.search(raw_full)
                                if m:
                                    cleaned = (raw_full[:m.start()] + raw_full[m.end():]).lstrip()
                                    picks_hidden = True
                                    if cleaned:
                                        yield _sse("token", {"text": cleaned})
                                elif len(raw_full) < 160:
                                    continue  # keep buffering, JSON may still arrive
                                else:
                                    picks_hidden = True
                                    yield _sse("token", {"text": raw_full})
                            else:
                                yield _sse("token", {"text": delta})
            except Exception as e:
                metrics.incr("recommendations.llm_errors")
                logger.error("Streaming recommendation failed: %s", e)
                yield _sse("error", {"message": "generation_failed"})

        # Finalise: parse picks, resolve products, per-product sizing.
        pick_indices, narrative = _parse_picks(raw_full, len(prompt_products))
        if pick_indices:
            recommended_products = [prompt_products[i] for i in pick_indices]
            metrics.incr("recommendations.llm_grounded")
        else:
            recommended_products = prompt_products[: ctx["effective_pick_limit"]]
        recommendations_text = (narrative.strip() if narrative else "") or _build_fallback_text(
            answers, calculated_size
        )

        recommended_ids = []
        for p in recommended_products:
            _annotate_product_size(
                p, ctx["measurements"], ctx["gender"], ctx["body_model"], calculated_size,
            )
            p.pop("_requested_type", None)
            if p.get("id") is not None:
                recommended_ids.append(str(p.get("id")))

        try:
            await events.record_async(
                events.EVENT_RECOMMENDATION_SHOWN,
                user_id=current_user["id"],
                upload_id=ctx["upload_id"],
                product_ids=recommended_ids,
                product_source=product_source,
                llm_grounded=bool(pick_indices),
                calculated_size=calculated_size,
                streamed=True,
            )
        except Exception:
            pass

        yield _sse("done", {
            "products": recommended_products,
            "recommended_ids": recommended_ids,
            "product_source": product_source,
            "llm_grounded": bool(pick_indices),
            "recommendations_text": recommendations_text,
            "calculated_size": ctx["calculated_size_info"],
            "gender": ctx["gender"],
            "body_model": ctx["body_model"],
        })

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/feedback")
async def recommendation_feedback(
    body: FeedbackRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Record storefront feedback (clicks, cart, purchase, size/fit).

    This is the durable signal that powers future learning-to-rank and
    size-accuracy models. See app.services.events for canonical event types.
    """
    allowed = {
        "product_clicked": events.EVENT_PRODUCT_CLICKED,
        "added_to_cart": events.EVENT_ADDED_TO_CART,
        "purchased": events.EVENT_PURCHASED,
        "size_feedback": events.EVENT_SIZE_FEEDBACK,
        "fit_feedback": events.EVENT_FIT_FEEDBACK,
    }
    event_type = allowed.get(body.event_type)
    if not event_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown event_type. Allowed: {sorted(allowed)}",
        )
    await events.record_async(
        event_type,
        user_id=current_user["id"],
        product_id=body.product_id,
        upload_id=body.upload_id,
        recommended_size=body.recommended_size,
        chosen_size=body.chosen_size,
        fit=body.fit,
        **(body.extra or {}),
    )
    metrics.incr(f"feedback.{body.event_type}")
    return {"status": "recorded", "event_type": body.event_type}
