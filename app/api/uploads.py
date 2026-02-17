"""
Photo upload API endpoints.
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status

from app.config import settings
from app.core.dependencies import CurrentUser, Storage
from app.schemas import (
    PhotoUploadListResponse,
    PhotoUploadResponse,
)
from app.schemas.photo_upload import GenderEnum
from app.schemas.processing import ProcessingResponse, ProcessingStatus, ProcessingTriggerResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _upload_to_response(upload: dict) -> PhotoUploadResponse:
    """Convert upload dict to PhotoUploadResponse."""
    uploaded_at = upload.get("uploaded_at")
    if isinstance(uploaded_at, str):
        uploaded_at = datetime.fromisoformat(uploaded_at)

    processed_at = upload.get("processed_at")
    if isinstance(processed_at, str):
        processed_at = datetime.fromisoformat(processed_at)

    return PhotoUploadResponse(
        id=upload["id"],
        user_id=upload.get("user_id"),
        image1=upload["image1"],
        image2=upload.get("image2"),
        image3=upload.get("image3"),
        height_cm=upload.get("height_cm"),
        weight_kg=upload.get("weight_kg"),
        gender=upload.get("gender", "male"),
        uploaded_at=uploaded_at,
        processed_at=processed_at,
        is_processed=upload.get("is_processed", False),
    )


def _validate_image(file: UploadFile) -> List[str]:
    """Validate an uploaded image file."""
    errors = []

    if not file or not file.filename:
        return errors

    # Check file extension
    filename = file.filename.lower()
    ext = Path(filename).suffix
    if ext not in settings.allowed_image_extensions:
        errors.append(
            f"Invalid file extension '{ext}'. "
            f"Allowed: {', '.join(settings.allowed_image_extensions)}"
        )

    # Check content type
    content_type = file.content_type
    if content_type and content_type not in settings.allowed_image_mime_types:
        errors.append(
            f"Invalid file type '{content_type}'. "
            f"Allowed: {', '.join(settings.allowed_image_mime_types)}"
        )

    return errors


async def _save_upload(file: UploadFile, upload_dir: Path) -> str:
    """Save an uploaded file and return the relative path."""
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename
    ext = Path(file.filename).suffix if file.filename else ".jpg"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / unique_name

    # Save file
    content = await file.read()
    file_path.write_bytes(content)

    return f"uploads/{unique_name}"


@router.get(
    "",
    response_model=PhotoUploadListResponse,
    summary="List user uploads",
)
async def list_uploads(
    current_user: CurrentUser,
    storage: Storage,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> PhotoUploadListResponse:
    """
    List all uploads for the current user.

    Args:
        current_user: Currently authenticated user
        storage: Redis storage instance
        page: Page number
        size: Items per page

    Returns:
        Paginated list of uploads
    """
    uploads, total = await storage.get_user_uploads(
        current_user["id"],
        page=page,
        size=size,
    )

    # Calculate pages
    pages = (total + size - 1) // size if total > 0 else 1

    return PhotoUploadListResponse(
        items=[_upload_to_response(u) for u in uploads],
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


@router.post(
    "",
    response_model=PhotoUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new upload",
)
async def create_upload(
    current_user: CurrentUser,
    storage: Storage,
    image1: UploadFile = File(..., description="Front view image (required)"),
    image2: Optional[UploadFile] = File(None, description="T-pose view image"),
    image3: Optional[UploadFile] = File(None, description="Side view image"),
    height_cm: Optional[float] = Form(None, ge=50, le=250),
    weight_kg: Optional[float] = Form(None, ge=20, le=250),
    gender: GenderEnum = Form(GenderEnum.MALE),
) -> PhotoUploadResponse:
    """
    Upload photos for body measurement.

    Args:
        current_user: Currently authenticated user
        storage: Redis storage instance
        image1: Front view image (required)
        image2: T-pose view image (optional)
        image3: Side view image (optional)
        height_cm: User height in cm
        weight_kg: User weight in kg
        gender: User gender

    Returns:
        Created upload data

    Raises:
        HTTPException: If validation fails
    """
    errors = []

    # Validate required image
    errors.extend(_validate_image(image1))

    # Validate optional images
    if image2 and image2.filename:
        errors.extend([f"image2: {e}" for e in _validate_image(image2)])
    if image3 and image3.filename:
        errors.extend([f"image3: {e}" for e in _validate_image(image3)])

    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=errors,
        )

    # Save uploaded files
    upload_dir = settings.media_path / "uploads"

    image1_path = await _save_upload(image1, upload_dir)
    image2_path = None
    image3_path = None

    if image2 and image2.filename:
        image2_path = await _save_upload(image2, upload_dir)
    if image3 and image3.filename:
        image3_path = await _save_upload(image3, upload_dir)

    # Create upload record in Redis
    upload_id = uuid.uuid4().hex
    upload = await storage.create_upload(
        upload_id=upload_id,
        user_id=current_user["id"],
        image1=image1_path,
        image2=image2_path,
        image3=image3_path,
        height_cm=height_cm,
        weight_kg=weight_kg,
        gender=gender.value,
    )

    logger.info(f"Upload created: id={upload['id']}, user={current_user['username']}")

    return _upload_to_response(upload)


@router.get(
    "/{upload_id}",
    response_model=PhotoUploadResponse,
    summary="Get upload by ID",
)
async def get_upload(
    upload_id: str,
    current_user: CurrentUser,
    storage: Storage,
) -> PhotoUploadResponse:
    """
    Get a specific upload by ID.

    Args:
        upload_id: Upload ID
        current_user: Currently authenticated user
        storage: Redis storage instance

    Returns:
        Upload data

    Raises:
        HTTPException: If upload not found or not owned by user
    """
    upload = await storage.get_upload(upload_id)

    if not upload or upload.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    return _upload_to_response(upload)


@router.delete(
    "/{upload_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete upload",
)
async def delete_upload(
    upload_id: str,
    current_user: CurrentUser,
    storage: Storage,
) -> None:
    """
    Delete an upload and its associated files.

    Args:
        upload_id: Upload ID
        current_user: Currently authenticated user
        storage: Redis storage instance

    Raises:
        HTTPException: If upload not found or not owned by user
    """
    upload = await storage.get_upload(upload_id)

    if not upload or upload.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    # Delete files
    media_root = settings.media_path
    for image_path in [upload.get("image1"), upload.get("image2"), upload.get("image3")]:
        if image_path:
            full_path = media_root / image_path
            if full_path.exists():
                full_path.unlink()

    # Delete from Redis
    await storage.delete_upload(upload_id)

    logger.info(f"Upload deleted: id={upload_id}, user={current_user['username']}")


@router.post(
    "/{upload_id}/process",
    response_model=ProcessingTriggerResponse,
    summary="Trigger processing for upload",
)
async def trigger_processing(
    upload_id: str,
    current_user: CurrentUser,
    storage: Storage,
) -> ProcessingTriggerResponse:
    """
    Trigger PARE processing for an upload.

    Args:
        upload_id: Upload ID
        current_user: Currently authenticated user
        storage: Redis storage instance

    Returns:
        Processing trigger response

    Raises:
        HTTPException: If upload not found or already processed
    """
    upload = await storage.get_upload(upload_id)

    if not upload or upload.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    # Check if already processed
    if upload.get("is_processed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload already processed",
        )

    # Check if minimum images are available
    if not all([upload.get("image1"), upload.get("image2"), upload.get("image3")]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All three images (front, T-pose, side) are required for processing",
        )

    # Default values if not provided
    height_cm = upload.get("height_cm") or 175.0
    weight_kg = upload.get("weight_kg") or 80.0
    gender = upload.get("gender") or "male"

    # Trigger Celery task if enabled
    if settings.celery_enabled:
        from app.tasks.processing import process_upload_pare

        task = process_upload_pare.delay(upload_id, height_cm, weight_kg, gender)
        logger.info(f"Processing task queued: upload_id={upload_id}, task_id={task.id}")

        return ProcessingTriggerResponse(
            message="Processing started",
            upload_id=upload_id,
            task_id=task.id,
            status=ProcessingStatus.PROCESSING,
        )
    else:
        # Run synchronously if Celery is disabled
        from app.services.processing_service import ProcessingService

        service = ProcessingService()
        await service.process_upload(storage, upload_id, height_cm, weight_kg, gender)

        logger.info(f"Processing completed synchronously: upload_id={upload_id}")

        return ProcessingTriggerResponse(
            message="Processing completed",
            upload_id=upload_id,
            task_id=None,
            status=ProcessingStatus.COMPLETED,
        )


@router.get(
    "/{upload_id}/results",
    response_model=ProcessingResponse,
    summary="Get processing results",
)
async def get_processing_results(
    upload_id: str,
    current_user: CurrentUser,
    storage: Storage,
) -> ProcessingResponse:
    """
    Get processing results for an upload.

    Args:
        upload_id: Upload ID
        current_user: Currently authenticated user
        storage: Redis storage instance

    Returns:
        Processing results

    Raises:
        HTTPException: If upload not found or not processed
    """
    upload = await storage.get_upload(upload_id)

    if not upload or upload.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    if not upload.get("is_processed"):
        return ProcessingResponse(
            upload_id=upload_id,
            status=ProcessingStatus.PENDING,
        )

    # Parse stored results
    processing_results = upload.get("processing_results")
    if processing_results:
        if isinstance(processing_results, str):
            results = json.loads(processing_results)
        else:
            results = processing_results
        return ProcessingResponse(
            upload_id=upload_id,
            status=ProcessingStatus.COMPLETED,
            **results,
        )

    return ProcessingResponse(
        upload_id=upload_id,
        status=ProcessingStatus.COMPLETED,
    )
