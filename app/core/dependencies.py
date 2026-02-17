"""
FastAPI dependencies for Redis storage and authentication.
"""
from typing import Annotated, Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database import RedisStorage, get_storage

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)


async def get_redis_storage() -> RedisStorage:
    """
    Dependency that provides Redis storage instance.

    Returns:
        RedisStorage: Storage instance
    """
    return await get_storage()


# Type alias for storage dependency
Storage = Annotated[RedisStorage, Depends(get_redis_storage)]


async def get_current_user(
    storage: Storage,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
    """
    Dependency to get the current authenticated user from token.

    Args:
        storage: Redis storage instance
        credentials: Bearer token credentials

    Returns:
        User dict if authenticated, None otherwise
    """
    if not credentials:
        return None

    token_key = credentials.credentials

    # Get token from Redis
    token_data = await storage.get_token(token_key)
    if not token_data:
        return None

    # Get user from Redis
    user = await storage.get_user_by_id(token_data["user_id"])
    if not user or not user.get("is_active", False):
        return None

    return user


async def get_current_active_user(
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Dependency to require an authenticated active user.

    Args:
        current_user: Current user from get_current_user

    Returns:
        User dict if authenticated and active

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
