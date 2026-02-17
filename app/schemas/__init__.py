"""
Pydantic schemas for request/response validation.
"""
from app.schemas.user import (
    UserCreate,
    UserResponse,
    UserUpdate,
    LoginRequest,
    TokenResponse,
    ChangePasswordRequest,
)
from app.schemas.photo_upload import (
    PhotoUploadCreate,
    PhotoUploadResponse,
    PhotoUploadListResponse,
)
from app.schemas.processing import (
    MeasurementResult,
    ProcessingResponse,
    ProcessingStatus,
)

__all__ = [
    # User schemas
    "UserCreate",
    "UserResponse",
    "UserUpdate",
    "LoginRequest",
    "TokenResponse",
    "ChangePasswordRequest",
    # Photo upload schemas
    "PhotoUploadCreate",
    "PhotoUploadResponse",
    "PhotoUploadListResponse",
    # Processing schemas
    "MeasurementResult",
    "ProcessingResponse",
    "ProcessingStatus",
]
