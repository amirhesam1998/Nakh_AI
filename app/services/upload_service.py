"""
Upload service for handling file uploads.
"""
import logging
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import PhotoUpload

logger = logging.getLogger(__name__)


class UploadService:
    """Service for upload operations."""

    # Allowed image extensions and MIME types
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
    ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/heic", "image/heif"}
    MAX_SIZE_MB = 10

    @staticmethod
    def validate_image(
        filename: str,
        content_type: Optional[str],
        size_bytes: int,
    ) -> List[str]:
        """
        Validate an uploaded image.

        Args:
            filename: Original filename
            content_type: MIME type
            size_bytes: File size in bytes

        Returns:
            List of validation error messages
        """
        errors = []

        # Check extension
        ext = Path(filename).suffix.lower()
        if ext not in UploadService.ALLOWED_EXTENSIONS:
            errors.append(
                f"Invalid file extension '{ext}'. "
                f"Allowed: {', '.join(UploadService.ALLOWED_EXTENSIONS)}"
            )

        # Check MIME type
        if content_type and content_type not in UploadService.ALLOWED_MIME_TYPES:
            errors.append(
                f"Invalid file type '{content_type}'. "
                f"Allowed: {', '.join(UploadService.ALLOWED_MIME_TYPES)}"
            )

        # Check file size
        size_mb = size_bytes / (1024 * 1024)
        if size_mb > UploadService.MAX_SIZE_MB:
            errors.append(
                f"File too large ({size_mb:.1f} MB). "
                f"Maximum: {UploadService.MAX_SIZE_MB} MB"
            )

        return errors

    @staticmethod
    def validate_image_header(content: bytes) -> bool:
        """
        Validate image content by checking magic numbers.

        Args:
            content: File content bytes

        Returns:
            True if valid image format
        """
        if len(content) < 10:
            return False

        header = content[:10]

        # JPEG: FF D8 FF
        is_jpeg = header[:3] == b"\xff\xd8\xff"

        # PNG: 89 50 4E 47 0D 0A 1A 0A
        is_png = header[:8] == b"\x89PNG\r\n\x1a\n"

        # HEIC: usually contains "ftyp"
        is_heic = b"ftyp" in header

        return is_jpeg or is_png or is_heic

    @staticmethod
    async def save_file(
        content: bytes,
        original_filename: str,
        upload_dir: Path,
    ) -> str:
        """
        Save uploaded file content to disk.

        Args:
            content: File content bytes
            original_filename: Original filename for extension
            upload_dir: Directory to save to

        Returns:
            Relative path from media root
        """
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        ext = Path(original_filename).suffix.lower() or ".jpg"
        unique_name = f"{uuid.uuid4().hex}{ext}"
        file_path = upload_dir / unique_name

        # Write file
        file_path.write_bytes(content)

        # Return relative path
        return f"uploads/{unique_name}"

    @staticmethod
    async def delete_file(relative_path: str, media_root: Path) -> bool:
        """
        Delete a file from disk.

        Args:
            relative_path: Path relative to media root
            media_root: Media root directory

        Returns:
            True if file was deleted
        """
        full_path = media_root / relative_path
        if full_path.exists():
            full_path.unlink()
            return True
        return False

    @staticmethod
    async def get_user_uploads(
        db: AsyncSession,
        user_id: int,
        page: int = 1,
        size: int = 20,
    ) -> Tuple[List[PhotoUpload], int]:
        """
        Get paginated uploads for a user.

        Args:
            db: Database session
            user_id: User ID
            page: Page number (1-indexed)
            size: Items per page

        Returns:
            Tuple of (uploads, total_count)
        """
        # Count total
        count_stmt = (
            select(func.count())
            .select_from(PhotoUpload)
            .where(PhotoUpload.user_id == user_id)
        )
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        # Get items
        offset = (page - 1) * size
        stmt = (
            select(PhotoUpload)
            .where(PhotoUpload.user_id == user_id)
            .order_by(PhotoUpload.uploaded_at.desc())
            .offset(offset)
            .limit(size)
        )
        result = await db.execute(stmt)
        uploads = list(result.scalars().all())

        return uploads, total

    @staticmethod
    async def create_upload(
        db: AsyncSession,
        user_id: int,
        image1_path: str,
        image2_path: Optional[str] = None,
        image3_path: Optional[str] = None,
        height_cm: Optional[float] = None,
        weight_kg: Optional[float] = None,
        gender: str = "male",
    ) -> PhotoUpload:
        """
        Create a new upload record.

        Args:
            db: Database session
            user_id: User ID
            image1_path: Path to first image
            image2_path: Path to second image
            image3_path: Path to third image
            height_cm: User height
            weight_kg: User weight
            gender: User gender

        Returns:
            Created PhotoUpload
        """
        upload = PhotoUpload(
            user_id=user_id,
            image1=image1_path,
            image2=image2_path,
            image3=image3_path,
            height_cm=height_cm,
            weight_kg=weight_kg,
            gender=gender,
        )
        db.add(upload)
        await db.flush()

        logger.info(f"Upload created: id={upload.id}")
        return upload

    @staticmethod
    async def delete_upload(
        db: AsyncSession,
        upload: PhotoUpload,
        media_root: Path,
    ) -> None:
        """
        Delete an upload and its associated files.

        Args:
            db: Database session
            upload: PhotoUpload to delete
            media_root: Media root directory
        """
        upload_id = upload.id

        # Delete files
        for image_path in [upload.image1, upload.image2, upload.image3]:
            if image_path:
                await UploadService.delete_file(image_path, media_root)

        # Delete record
        await db.delete(upload)

        logger.info(f"Upload deleted: id={upload_id}")
