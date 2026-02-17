"""
Authentication API endpoints.
"""
import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.dependencies import CurrentUser, Storage
from app.core.security import generate_token, hash_password, verify_password
from app.schemas import (
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _user_to_response(user: dict) -> UserResponse:
    """Convert user dict to UserResponse."""
    from datetime import datetime
    created_at = user.get("created_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    return UserResponse(
        id=user["id"],
        username=user["username"],
        email=user["email"],
        is_active=user.get("is_active", True),
        created_at=created_at,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(user_data: UserCreate, storage: Storage) -> TokenResponse:
    """
    Register a new user account.

    Args:
        user_data: User registration data
        storage: Redis storage instance

    Returns:
        Token and user data

    Raises:
        HTTPException: If username or email already exists
    """
    # Check if username exists
    existing = await storage.get_user_by_username(user_data.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Check if email exists
    existing = await storage.get_user_by_email(user_data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user
    user_id = uuid.uuid4().hex
    user = await storage.create_user(
        user_id=user_id,
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
    )

    # Create token
    token_key = generate_token()
    await storage.create_token(token_key, user_id)

    logger.info(f"User registered: {user['username']}")

    return TokenResponse(
        token=token_key,
        user=_user_to_response(user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and get authentication token",
)
async def login(login_data: LoginRequest, storage: Storage) -> TokenResponse:
    """
    Authenticate user and return token.

    Args:
        login_data: Login credentials
        storage: Redis storage instance

    Returns:
        Token and user data

    Raises:
        HTTPException: If credentials are invalid
    """
    # Find user by username
    user = await storage.get_user_by_username(login_data.username)

    if not user or not verify_password(login_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user.get("is_active", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    # Create new token (old tokens expire automatically via TTL)
    token_key = generate_token()
    await storage.create_token(token_key, user["id"])

    logger.info(f"User logged in: {user['username']}")

    return TokenResponse(
        token=token_key,
        user=_user_to_response(user),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout and invalidate token",
)
async def logout(current_user: CurrentUser, storage: Storage) -> None:
    """
    Logout user by deleting their tokens.

    Args:
        current_user: Currently authenticated user
        storage: Redis storage instance
    """
    # Delete all tokens for this user
    await storage.delete_user_tokens(current_user["id"])

    logger.info(f"User logged out: {current_user['username']}")
