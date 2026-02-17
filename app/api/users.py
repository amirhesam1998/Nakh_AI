"""
User profile API endpoints.
"""
import logging

from fastapi import APIRouter, HTTPException, status

from app.core.dependencies import CurrentUser, Storage
from app.core.security import hash_password, verify_password
from app.schemas import ChangePasswordRequest, UserResponse, UserUpdate

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


@router.get(
    "/profile",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_profile(current_user: CurrentUser) -> UserResponse:
    """
    Get the current user's profile.

    Args:
        current_user: Currently authenticated user

    Returns:
        User profile data
    """
    return _user_to_response(current_user)


@router.patch(
    "/profile",
    response_model=UserResponse,
    summary="Update current user profile",
)
async def update_profile(
    update_data: UserUpdate,
    current_user: CurrentUser,
    storage: Storage,
) -> UserResponse:
    """
    Update the current user's profile.

    Args:
        update_data: Fields to update
        current_user: Currently authenticated user
        storage: Redis storage instance

    Returns:
        Updated user profile

    Raises:
        HTTPException: If username or email already exists
    """
    updates = {}

    # Check if new username is available
    if update_data.username and update_data.username != current_user["username"]:
        existing = await storage.get_user_by_username(update_data.username)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )
        updates["username"] = update_data.username

    # Check if new email is available
    if update_data.email and update_data.email != current_user["email"]:
        existing = await storage.get_user_by_email(update_data.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        updates["email"] = update_data.email

    if updates:
        updated_user = await storage.update_user(current_user["id"], updates)
        logger.info(f"User profile updated: {updated_user['username']}")
        return _user_to_response(updated_user)

    return _user_to_response(current_user)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change current user password",
)
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: CurrentUser,
    storage: Storage,
) -> None:
    """
    Change the current user's password.

    Args:
        password_data: Current and new password
        current_user: Currently authenticated user
        storage: Redis storage instance

    Raises:
        HTTPException: If current password is incorrect
    """
    # Verify current password
    if not verify_password(password_data.current_password, current_user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Update password
    await storage.update_user(
        current_user["id"],
        {"hashed_password": hash_password(password_data.new_password)},
    )

    logger.info(f"Password changed for user: {current_user['username']}")
