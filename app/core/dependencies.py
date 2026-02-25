"""
FastAPI dependencies for authentication via e-commerce service proxy.
"""
import json
import logging
import time
from typing import Annotated, Any, Dict, Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.database import RedisStorage, get_storage

logger = logging.getLogger(__name__)

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)

# In-memory auth cache: token -> (user_data, expiry_timestamp)
_auth_cache: Dict[str, tuple] = {}


async def get_redis_storage() -> RedisStorage:
    """
    Dependency that provides Redis storage instance.

    Returns:
        RedisStorage: Storage instance
    """
    return await get_storage()


# Type alias for storage dependency
Storage = Annotated[RedisStorage, Depends(get_redis_storage)]


def _get_cached_user(token: str) -> Optional[Dict[str, Any]]:
    """Check in-memory cache for a validated token."""
    entry = _auth_cache.get(token)
    if entry:
        user_data, expiry = entry
        if time.time() < expiry:
            return user_data
        else:
            del _auth_cache[token]
    return None


def _set_cached_user(token: str, user_data: Dict[str, Any]) -> None:
    """Store validated user in in-memory cache."""
    expiry = time.time() + settings.auth_cache_ttl_seconds
    _auth_cache[token] = (user_data, expiry)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
    """
    Validate the Bearer token by proxying to the e-commerce service.
    Caches successful results in memory to avoid hitting the e-commerce
    service on every request.
    """
    if not credentials:
        return None

    token = credentials.credentials

    # Check in-memory cache first
    cached = _get_cached_user(token)
    if cached:
        return cached

    # Validate token against e-commerce service
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                settings.ecommerce_auth_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "x-api-key": settings.ecommerce_api_key,
                    "Accept": "application/json",
                },
            )
    except Exception as e:
        logger.error(f"Failed to reach e-commerce auth service: {e}")
        return None

    if response.status_code != 200:
        logger.debug(f"E-commerce auth returned {response.status_code}")
        return None

    try:
        data = response.json()
    except Exception:
        logger.warning("E-commerce auth returned non-JSON response")
        return None

    # Extract user from response
    # Handles: {result: {user: {...}}}, {result: {id, ...}}, {user: {...}}, {id, ...}
    user = None
    if isinstance(data, dict):
        result = data.get("result")
        if isinstance(result, dict):
            if "user" in result and isinstance(result["user"], dict):
                user = result["user"]
            elif "id" in result:
                user = result
        if not user and "user" in data and isinstance(data["user"], dict):
            user = data["user"]
        if not user and "id" in data:
            user = data

    if not user:
        logger.warning(
            f"Could not extract user from e-commerce response: "
            f"{list(data.keys()) if isinstance(data, dict) else type(data)}"
        )
        return None

    # Normalize to a dict with at least an "id" field
    user_data = {
        "id": str(user.get("id", "")),
        "username": user.get("username", ""),
        "email": user.get("email", ""),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "is_active": True,
    }

    # Cache in memory
    _set_cached_user(token, user_data)

    return user_data


async def get_current_active_user(
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Dependency to require an authenticated active user.

    Raises:
        HTTPException: If not authenticated or user is inactive
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not current_user.get("is_active", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return current_user


# Type aliases for user dependencies
CurrentUser = Annotated[Dict[str, Any], Depends(get_current_active_user)]
OptionalUser = Annotated[Optional[Dict[str, Any]], Depends(get_current_user)]
