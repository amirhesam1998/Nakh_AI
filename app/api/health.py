"""
Health check API endpoint.
"""
from typing import Dict

from fastapi import APIRouter

from app.database import get_redis

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
