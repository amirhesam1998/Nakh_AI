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

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from app.config import settings
from app.core.dependencies import CurrentUser
from app.schemas import (
    PhotoUploadListResponse,
    PhotoUploadResponse,
)
from app.schemas.photo_upload import GenderEnum
from app.schemas.processing import ProcessingResponse, ProcessingStatus, ProcessingTriggerResponse


class QuestionnaireRequest(BaseModel):
    completedAt: Optional[str] = None
    answers: dict = {}
    upload_id: Optional[str] = None

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


def _run_processing_in_background(upload_id: str, height_cm: float, weight_kg: float, gender: str, age: int = 25) -> None:
    """Submit PARE processing to the background thread pool."""
    from app.tasks.processing import _process_upload_pare_impl

    class _MockTask:
        def retry(self, *args, **kwargs):
            raise kwargs.get("exc", Exception("Task retry"))

    def _worker():
        try:
            _process_upload_pare_impl(_MockTask(), upload_id, height_cm, weight_kg, gender, age=age)
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
        image4=upload.get("image4"),
        height_cm=upload.get("height_cm"),
        weight_kg=upload.get("weight_kg"),
        age=upload.get("age"),
        gender=upload.get("gender", "male"),
        uploaded_at=uploaded_at,
        processed_at=processed_at,
        is_processed=upload.get("is_processed", False),
    )


# Formats that need auto-conversion to JPG
_CONVERT_EXTENSIONS = {".heic", ".heif", ".webp"}

# Persian error messages
_PERSIAN_ERRORS = {
    "unsupported_format": "فرمت تصویر پشتیبانی نمی‌شود. لطفاً تصویر دیگری انتخاب کنید.",
    "corrupted": "فایل تصویر خراب است و قابل پردازش نیست. لطفاً دوباره تلاش کنید.",
    "empty_file": "فایل تصویر خالی است. لطفاً دوباره تلاش کنید.",
    "low_quality": "کیفیت تصویر بسیار پایین است. لطفاً عکس واضح‌تری ثبت کنید.",
    "upload_failed": "آپلود تصویر با مشکل مواجه شد. لطفاً اتصال اینترنت خود را بررسی کرده و دوباره تلاش کنید.",
}


def _validate_image(file: UploadFile) -> List[str]:
    """Validate an uploaded image file with Persian error messages."""
    errors = []

    if not file or not file.filename:
        return errors

    # Check file extension
    filename = file.filename.lower()
    ext = Path(filename).suffix
    if ext not in settings.allowed_image_extensions:
        errors.append(_PERSIAN_ERRORS["unsupported_format"])

    # Check content type (lenient: some mobile browsers send wrong MIME)
    content_type = file.content_type
    if content_type and not content_type.startswith("image/"):
        errors.append(_PERSIAN_ERRORS["unsupported_format"])

    return errors


def _convert_to_jpg(content: bytes) -> bytes:
    """Convert image bytes (HEIC/HEIF/WEBP/etc.) to JPEG bytes.

    Registers HEIF opener on first call so Pillow can handle HEIC/HEIF.
    Returns original bytes if already JPEG/PNG or conversion fails.
    """
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    from PIL import Image
    import io

    try:
        img = Image.open(io.BytesIO(content))
        # Convert to RGB if needed (RGBA, palette, etc.)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"Image conversion failed: {e}")
        raise


def _validate_image_content(content: bytes, filename: str) -> List[str]:
    """Deep validation of image content: corruption, resolution, format."""
    errors = []

    if not content or len(content) == 0:
        errors.append(_PERSIAN_ERRORS["empty_file"])
        return errors

    from PIL import Image
    import io

    try:
        # Register HEIF support
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass

        img = Image.open(io.BytesIO(content))
        img.verify()  # Check for corruption

        # Re-open after verify (verify closes the image)
        img = Image.open(io.BytesIO(content))
        w, h = img.size

        # Check minimum resolution
        min_res = settings.min_image_resolution
        if w < min_res and h < min_res:
            errors.append(_PERSIAN_ERRORS["low_quality"])

    except Exception:
        errors.append(_PERSIAN_ERRORS["corrupted"])

    return errors


async def _save_upload_file(file: UploadFile, upload_dir: Path) -> str:
    """Save an uploaded file, auto-converting unsupported formats to JPG.

    Returns the relative path (e.g. 'uploads/abc123.jpg').
    """
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix.lower() if file.filename else ".jpg"
    content = await file.read()

    # Auto-convert HEIC/HEIF/WEBP → JPG
    if ext in _CONVERT_EXTENSIONS:
        try:
            content = _convert_to_jpg(content)
            ext = ".jpg"
            logger.info(f"Auto-converted {file.filename} to JPG")
        except Exception as e:
            logger.error(f"Conversion failed for {file.filename}: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=[_PERSIAN_ERRORS["corrupted"]],
            )

    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / unique_name
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
    image1: UploadFile = File(..., description="Front A-Pose image (required)"),
    image2: Optional[UploadFile] = File(None, description="Side pose image"),
    image3: Optional[UploadFile] = File(None, description="Back A-Pose image"),
    image4: Optional[UploadFile] = File(None, description="Front T-Pose image"),
    height_cm: Optional[float] = Form(None, ge=50, le=250),
    weight_kg: Optional[float] = Form(None, ge=20, le=250),
    age: Optional[int] = Form(None, ge=3, le=120),
    gender: GenderEnum = Form(GenderEnum.MALE),
) -> PhotoUploadResponse:
    """Upload photos for body measurement.

    Requires 4 poses: Front A-Pose, Side, Back A-Pose, Front T-Pose.
    """
    errors = []

    # Validate file extensions / MIME types
    errors.extend(_validate_image(image1))
    if image2 and image2.filename:
        errors.extend(_validate_image(image2))
    if image3 and image3.filename:
        errors.extend(_validate_image(image3))
    if image4 and image4.filename:
        errors.extend(_validate_image(image4))

    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=errors,
        )

    # Deep content validation (corruption, resolution, empty file)
    all_images = [("image1", image1)]
    if image2 and image2.filename:
        all_images.append(("image2", image2))
    if image3 and image3.filename:
        all_images.append(("image3", image3))
    if image4 and image4.filename:
        all_images.append(("image4", image4))

    for img_label, img_file in all_images:
        content = await img_file.read()
        await img_file.seek(0)  # Reset for later save
        content_errors = _validate_image_content(content, img_file.filename or "")
        errors.extend(content_errors)

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
    image4_path = None

    if image2 and image2.filename:
        image2_path = await _save_upload_file(image2, upload_dir)
    if image3 and image3.filename:
        image3_path = await _save_upload_file(image3, upload_dir)
    if image4 and image4.filename:
        image4_path = await _save_upload_file(image4, upload_dir)

    # Create upload record as JSON file on disk
    upload_id = uuid.uuid4().hex
    upload_data = {
        "id": upload_id,
        "user_id": current_user["id"],
        "image1": image1_path,
        "image2": image2_path,
        "image3": image3_path,
        "image4": image4_path,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "age": age,
        "gender": gender.value,
        "uploaded_at": datetime.utcnow().isoformat(),
        "processed_at": None,
        "is_processed": False,
        "processing_results": None,
    }

    # Auto-trigger processing only when all 4 images AND height + weight + age are present.
    can_auto_process = bool(
        image1_path and image2_path and image3_path and image4_path
        and height_cm is not None and weight_kg is not None and age is not None
    )
    if can_auto_process:
        upload_data["processing_status"] = "processing"

    _save_metadata(upload_id, upload_data)

    logger.info(f"Upload created: id={upload_id}, user={current_user['username']}")

    if can_auto_process:
        _run_processing_in_background(
            upload_id,
            float(height_cm),
            float(weight_kg),
            gender.value,
            int(age),
        )
    elif image1_path and image2_path and image3_path and image4_path:
        logger.info(
            f"Upload {upload_id}: 4 images present but height/weight/age missing; "
            f"skipping auto-process. Caller must POST /uploads/{upload_id}/process "
            f"after supplying measurements."
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
    for image_path in [upload.get("image1"), upload.get("image2"), upload.get("image3"), upload.get("image4")]:
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

    if not all([upload.get("image1"), upload.get("image2"), upload.get("image3"), upload.get("image4")]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All four images (Front A-Pose, Side, Back A-Pose, Front T-Pose) are required for processing",
        )

    height_cm = upload.get("height_cm")
    weight_kg = upload.get("weight_kg")
    age = upload.get("age")
    if height_cm is None or weight_kg is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Both height_cm and weight_kg must be set on the upload before "
                "processing — they anchor the body-measurement scale."
            ),
        )
    if age is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Age must be set on the upload before processing.",
        )
    gender = upload.get("gender") or "male"

    if settings.celery_enabled:
        from app.tasks.processing import process_upload_pare

        task = process_upload_pare.delay(upload_id, height_cm, weight_kg, gender, age=int(age))
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

        _run_processing_in_background(upload_id, height_cm, weight_kg, gender, int(age))
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
    body: QuestionnaireRequest,
):
    """
    Save questionnaire answers into the upload's metadata JSON.

    Body: { "completedAt": "...", "answers": {...}, "upload_id": "..." }
    If upload_id is omitted the user's latest upload is used.
    """
    answers = body.answers
    completed_at = body.completedAt or datetime.utcnow().isoformat()
    upload_id = body.upload_id

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
