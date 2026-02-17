"""
Photo upload Pydantic schemas.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class GenderEnum(str, Enum):
    """Gender options for body measurements."""

    MALE = "male"
    FEMALE = "female"


class PhotoUploadCreate(BaseModel):
    """Schema for creating a photo upload (metadata only, files uploaded separately)."""

    height_cm: Optional[float] = Field(None, ge=50, le=250)
    weight_kg: Optional[float] = Field(None, ge=20, le=250)
    gender: GenderEnum = GenderEnum.MALE

    @field_validator("height_cm")
    @classmethod
    def validate_height(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 50 or v > 250):
            raise ValueError("Height must be between 50 and 250 cm")
        return v

    @field_validator("weight_kg")
    @classmethod
    def validate_weight(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 20 or v > 250):
            raise ValueError("Weight must be between 20 and 250 kg")
        return v


class PhotoUploadResponse(BaseModel):
    """Schema for photo upload response."""

    id: str
    user_id: Optional[str] = None
    image1: str
    image2: Optional[str] = None
    image3: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    gender: str
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    is_processed: bool

    @property
    def image_count(self) -> int:
        """Count of uploaded images."""
        return sum(1 for img in [self.image1, self.image2, self.image3] if img)


class PhotoUploadListResponse(BaseModel):
    """Schema for paginated list of photo uploads."""

    items: List[PhotoUploadResponse]
    total: int
    page: int
    size: int
    pages: int
