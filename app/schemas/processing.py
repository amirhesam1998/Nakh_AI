"""
Processing result Pydantic schemas.
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ProcessingStatus(str, Enum):
    """Processing status options."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MeasurementResult(BaseModel):
    """Schema for individual measurement result from a view."""

    label: str
    file_url: Optional[str] = None
    results: Dict[str, Any]
    pretty: Dict[str, str]


class ProcessingResponse(BaseModel):
    """Schema for processing response."""

    upload_id: str
    status: ProcessingStatus
    processed_urls: List[str] = []
    video_url: Optional[str] = None
    npz_urls: List[str] = []
    measurements: List[MeasurementResult] = []
    silhouette_url: Optional[str] = None
    mannequin_url: Optional[str] = None
    three_cfg: Optional[Dict[str, Any]] = None
    width_scale: Optional[float] = None
    bmi: Optional[float] = None
    errors: List[str] = []


class ProcessingTriggerResponse(BaseModel):
    """Schema for processing trigger response."""

    message: str
    upload_id: str
    task_id: Optional[str] = None
    status: ProcessingStatus = ProcessingStatus.PENDING
