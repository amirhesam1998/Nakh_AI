"""
Product recommendation endpoint.

Combines body measurements + questionnaire answers + mock product catalog
and asks the LLM for personalized recommendations in Persian.
"""
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.config import settings
from app.core.dependencies import get_current_active_user
from app.services.llm import llm_manager
from app.services.product_service import product_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recommendations", tags=["recommendations"])

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
    """Return the 'Average' measurement dict from processing results."""
    results = upload.get("processing_results") or {}
    measurements_list = results.get("measurements", [])
    for entry in measurements_list:
        if entry.get("label") == "Average":
            return entry.get("results", {})
    if measurements_list:
        return measurements_list[-1].get("results", {})
    return {}


def _build_prompt(measurements: dict, answers: dict, products: list[dict]) -> str:
    """Build a Persian prompt for the LLM."""
    meas_text = "\n".join(f"- {k}: {v}" for k, v in measurements.items() if v)

    answers_text = "\n".join(f"- {k}: {v}" for k, v in answers.items())

    product_lines = []
    for p in products[:10]:
        product_lines.append(
            f"  - {p.get('name_fa', p.get('name', '?'))} | "
            f"قیمت: {p.get('price', 0):,} تومان | "
            f"دسته: {p.get('category', '-')} | "
            f"پارچه: {p.get('fabric', '-')}"
        )
    products_text = "\n".join(product_lines)

    return f"""تو یک مشاور لباس حرفه‌ای هستی. بر اساس اندازه‌های بدن، ترجیحات کاربر و لیست محصولات موجود، پیشنهادات شخصی‌سازی‌شده ارائه بده.

اندازه‌های بدن:
{meas_text}

ترجیحات کاربر (پاسخ پرسشنامه):
{answers_text}

محصولات موجود:
{products_text}

لطفاً ۳ تا ۵ محصول مناسب پیشنهاد بده و دلیل انتخاب هر کدام را توضیح بده. پاسخ را به فارسی بنویس."""


@router.post("")
async def get_recommendations(
    current_user: dict = Depends(get_current_active_user),
    body: dict = Body(default={}),
):
    """
    Generate personalised product recommendations.

    Body: { "upload_id": "..." }  — uses latest upload if omitted.
    """
    upload_id = body.get("upload_id")

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

    # Fetch products (mock or real)
    products = await product_service.fetch_products(limit=20)

    # Build LLM prompt and generate
    recommendations_text = ""
    if llm_manager.is_ready:
        try:
            prompt = _build_prompt(measurements, answers, products)
            response = llm_manager.generate(
                prompt=prompt,
                max_new_tokens=1024,
                temperature=0.7,
            )
            recommendations_text = response.text
        except Exception as e:
            logger.error("LLM recommendation generation failed: %s", e)

    # Fallback static text
    if not recommendations_text:
        recommendations_text = (
            "بر اساس اندازه‌ها و ترجیحات شما، محصولات زیر پیشنهاد می‌شوند. "
            "برای مشاوره دقیق‌تر، لطفاً از بخش چت استفاده کنید."
        )

    return {
        "upload_id": upload_id,
        "recommendations_text": recommendations_text,
        "products": products[:5],
        "questionnaire_summary": answers,
    }
