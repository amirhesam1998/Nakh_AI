"""
Health check API endpoint.
"""
from typing import Dict

from fastapi import APIRouter

from app.config import settings
from app.database import get_redis
from app.services.metrics import metrics

router = APIRouter()


@router.get(
    "",
    summary="Health check",
    response_model=Dict[str, str],
)
async def health_check() -> Dict[str, str]:
    """
    Check application health status.

    Returns:
        Health status
    """
    # Check Redis connection
    try:
        redis = await get_redis()
        await redis.ping()
        redis_status = "healthy"
    except Exception:
        redis_status = "unhealthy"

    return {
        "status": "healthy" if redis_status == "healthy" else "degraded",
        "redis": redis_status,
    }


@router.get("/metrics", summary="Operational metrics snapshot")
async def metrics_snapshot() -> dict:
    """Return counters, latency summaries, and derived rates.

    Covers the signals we previously couldn't observe: LLM latency, PARE
    success rate & duration, mock/unavailable fallback rate, recommendation
    grounding rate, and measurement-confidence distribution.
    """
    if not getattr(settings, "metrics_enabled", True):
        return {"enabled": False}
    snap = metrics.snapshot()
    snap["enabled"] = True
    return snap
