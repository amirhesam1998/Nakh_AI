"""
Photo upload API endpoints.

Upload metadata is stored as JSON files on disk (no Redis/database required).
"""
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile, status

from app.config import settings
from app.core.dependencies import CurrentUser
from app.schemas import (
    PhotoUploadListResponse,
    PhotoUploadResponse,
)
from app.schemas.photo_upload import GenderEnum
from app.schemas.processing import ProcessingResponse, ProcessingStatus, ProcessingTriggerResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# Single-worker executor — PARE is GPU-heavy, serialized queue prevents OOM
_processing_executor = ThreadPoolExecutor(max_workers=1)

# Directory for upload metadata JSON files
METADATA_DIR = settings.media_path / "metadata"


def _ensure_metadata_dir() -> Path:
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    return METADATA_DIR


def _save_metadata(upload_id: str, data: dict) -> None:
    _ensure_metadata_dir()
    target = METADATA_DIR / f"{upload_id}.json"
    tmp = METADATA_DIR / f"{upload_id}.json.tmp"
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(target)


def _load_metadata(upload_id: str) -> Optional[dict]:
    path = METADATA_DIR / f"{upload_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _delete_metadata(upload_id: str) -> None:
    path = METADATA_DIR / f"{upload_id}.json"
    if path.exists():
        path.unlink()


def _list_user_metadata(user_id: str) -> List[dict]:
    _ensure_metadata_dir()
    uploads = []
    for path in METADATA_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if str(data.get("user_id")) == str(user_id):
                uploads.append(data)
        except Exception:
            continue
    uploads.sort(key=lambda u: u.get("uploaded_at", ""), reverse=True)
    return uploads


def _run_processing_in_background(upload_id: str, height_cm: float, weight_kg: float, gender: str) -> None:
    """Submit PARE processing to the background thread pool."""
    from app.tasks.processing import _process_upload_pare_impl

    class _MockTask:
        def retry(self, *args, **kwargs):
            raise kwargs.get("exc", Exception("Task retry"))

    def _worker():
        try:
            _process_upload_pare_impl(_MockTask(), upload_id, height_cm, weight_kg, gender)
        except Exception:
            logger.exception(f"Background processing failed for upload {upload_id}")

    _processing_executor.submit(_worker)
    logger.info(f"Submitted background processing for upload {upload_id}")


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
        user_id=str(upload.get("user_id", "")),
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


async def _save_upload_file(file: UploadFile, upload_dir: Path) -> str:
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
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> PhotoUploadListResponse:
    """List all uploads for the current user."""
    all_uploads = _list_user_metadata(current_user["id"])
    total = len(all_uploads)

    # Paginate
    start = (page - 1) * size
    page_uploads = all_uploads[start : start + size]

    pages = (total + size - 1) // size if total > 0 else 1

    return PhotoUploadListResponse(
        items=[_upload_to_response(u) for u in page_uploads],
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
    image1: UploadFile = File(..., description="Front view image (required)"),
    image2: Optional[UploadFile] = File(None, description="T-pose view image"),
    image3: Optional[UploadFile] = File(None, description="Side view image"),
    height_cm: Optional[float] = Form(None, ge=50, le=250),
    weight_kg: Optional[float] = Form(None, ge=20, le=250),
    gender: GenderEnum = Form(GenderEnum.MALE),
) -> PhotoUploadResponse:
    """Upload photos for body measurement."""
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

    image1_path = await _save_upload_file(image1, upload_dir)
    image2_path = None
    image3_path = None

    if image2 and image2.filename:
        image2_path = await _save_upload_file(image2, upload_dir)
    if image3 and image3.filename:
        image3_path = await _save_upload_file(image3, upload_dir)

    # Create upload record as JSON file on disk
    upload_id = uuid.uuid4().hex
    upload_data = {
        "id": upload_id,
        "user_id": current_user["id"],
        "image1": image1_path,
        "image2": image2_path,
        "image3": image3_path,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "gender": gender.value,
        "uploaded_at": datetime.utcnow().isoformat(),
        "processed_at": None,
        "is_processed": False,
        "processing_results": None,
    }

    # Auto-trigger processing if all 3 images are provided
    if image1_path and image2_path and image3_path:
        upload_data["processing_status"] = "processing"

    _save_metadata(upload_id, upload_data)

    logger.info(f"Upload created: id={upload_id}, user={current_user['username']}")

    # Kick off background PARE processing
    if upload_data.get("processing_status") == "processing":
        _run_processing_in_background(
            upload_id,
            height_cm or 175.0,
            weight_kg or 80.0,
            gender.value,
        )

    return _upload_to_response(upload_data)


@router.get(
    "/{upload_id}",
    response_model=PhotoUploadResponse,
    summary="Get upload by ID",
)
async def get_upload(
    upload_id: str,
    current_user: CurrentUser,
) -> PhotoUploadResponse:
    """Get a specific upload by ID."""
    upload = _load_metadata(upload_id)

    if not upload or str(upload.get("user_id")) != str(current_user["id"]):
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
) -> None:
    """Delete an upload and its associated files."""
    upload = _load_metadata(upload_id)

    if not upload or str(upload.get("user_id")) != str(current_user["id"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    # Delete image files
    media_root = settings.media_path
    for image_path in [upload.get("image1"), upload.get("image2"), upload.get("image3")]:
        if image_path:
            full_path = media_root / image_path
            if full_path.exists():
                full_path.unlink()

    # Delete metadata
    _delete_metadata(upload_id)

    logger.info(f"Upload deleted: id={upload_id}, user={current_user['username']}")


@router.post(
    "/{upload_id}/process",
    response_model=ProcessingTriggerResponse,
    summary="Trigger processing for upload",
)
async def trigger_processing(
    upload_id: str,
    current_user: CurrentUser,
) -> ProcessingTriggerResponse:
    """Trigger PARE processing for an upload."""
    upload = _load_metadata(upload_id)

    if not upload or str(upload.get("user_id")) != str(current_user["id"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    if upload.get("is_processed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload already processed",
        )

    if not all([upload.get("image1"), upload.get("image2"), upload.get("image3")]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All three images (front, T-pose, side) are required for processing",
        )

    height_cm = upload.get("height_cm") or 175.0
    weight_kg = upload.get("weight_kg") or 80.0
    gender = upload.get("gender") or "male"

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
        # Mark as processing and kick off background thread
        upload["processing_status"] = "processing"
        _save_metadata(upload_id, upload)

        _run_processing_in_background(upload_id, height_cm, weight_kg, gender)
        logger.info(f"Processing started in background: upload_id={upload_id}")

        return ProcessingTriggerResponse(
            message="Processing started",
            upload_id=upload_id,
            task_id=None,
            status=ProcessingStatus.PROCESSING,
        )


@router.get(
    "/{upload_id}/results",
    response_model=ProcessingResponse,
    summary="Get processing results",
)
async def get_processing_results(
    upload_id: str,
    current_user: CurrentUser,
) -> ProcessingResponse:
    """Get processing results for an upload."""
    upload = _load_metadata(upload_id)

    if not upload or str(upload.get("user_id")) != str(current_user["id"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    processing_status = upload.get("processing_status")

    if processing_status == "processing":
        return ProcessingResponse(
            upload_id=upload_id,
            status=ProcessingStatus.PROCESSING,
        )

    if not upload.get("is_processed"):
        return ProcessingResponse(
            upload_id=upload_id,
            status=ProcessingStatus.PENDING,
        )

    processing_results = upload.get("processing_results")
    if processing_results:
        if isinstance(processing_results, str):
            results = json.loads(processing_results)
        else:
            results = processing_results

        # Remove keys that conflict with explicit kwargs
        results.pop("status", None)
        results.pop("upload_id", None)

        return ProcessingResponse(
            upload_id=upload_id,
            status=ProcessingStatus.COMPLETED,
            **results,
        )

    return ProcessingResponse(
        upload_id=upload_id,
        status=ProcessingStatus.COMPLETED,
    )


@router.post(
    "/questionnaire",
    summary="Save questionnaire answers",
)
async def save_questionnaire(
    current_user: CurrentUser,
    body: dict = Body(...),
):
    """
    Save questionnaire answers into the upload's metadata JSON.

    Body: { "completedAt": "...", "answers": {...}, "upload_id": "..." }
    If upload_id is omitted the user's latest upload is used.
    """
    answers = body.get("answers", {})
    completed_at = body.get("completedAt", datetime.utcnow().isoformat())
    upload_id = body.get("upload_id")

    if not upload_id:
        # Find user's latest upload
        uploads = _list_user_metadata(current_user["id"])
        if not uploads:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No uploads found for this user",
            )
        upload_id = uploads[0]["id"]

    upload = _load_metadata(upload_id)
    if not upload or str(upload.get("user_id")) != str(current_user["id"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    upload["questionnaire"] = {
        "completed_at": completed_at,
        "answers": answers,
    }
    _save_metadata(upload_id, upload)

    logger.info(f"Questionnaire saved for upload {upload_id}")

    return {"message": "Questionnaire saved successfully", "upload_id": upload_id}
