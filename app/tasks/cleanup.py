"""
Media cleanup Celery task.
"""
import logging
import time
from pathlib import Path
from typing import Any, Dict

from app.config import settings

logger = logging.getLogger(__name__)


# Conditional import based on Celery availability
if settings.celery_enabled:
    from app.tasks.celery_app import celery_app

    @celery_app.task
    def cleanup_old_media_files(days_old: int = 7) -> Dict[str, Any]:
        """Background task to clean up old media files."""
        return _cleanup_old_media_files_impl(days_old)
else:
    def cleanup_old_media_files(days_old: int = 7) -> Dict[str, Any]:
        """Synchronous fallback when Celery is disabled."""
        return _cleanup_old_media_files_impl(days_old)

    cleanup_old_media_files.delay = cleanup_old_media_files
    cleanup_old_media_files.apply_async = lambda *a, **kw: cleanup_old_media_files(*a, **kw)


def _cleanup_old_media_files_impl(days_old: int = 7) -> Dict[str, Any]:
    """
    Implementation of media cleanup task.

    Args:
        days_old: Delete files older than this many days

    Returns:
        Dictionary with cleanup statistics
    """
    logger.info(f"Starting media cleanup (files older than {days_old} days)")

    cutoff_time = time.time() - (days_old * 24 * 60 * 60)
    deleted_count = 0
    deleted_size = 0

    media_root = settings.media_path
    cleanup_dirs = ["processed", "videos", "body_models", "AI_Processing/pre"]

    for dir_name in cleanup_dirs:
        dir_path = media_root / dir_name
        if not dir_path.exists():
            continue

        for file_path in dir_path.rglob("*"):
            if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                try:
                    size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    deleted_size += size
                    logger.debug(f"Deleted: {file_path}")
                except Exception as e:
                    logger.warning(f"Could not delete {file_path}: {e}")

    deleted_size_mb = deleted_size / 1024 / 1024
    logger.info(f"Cleanup completed: {deleted_count} files, {deleted_size_mb:.2f} MB")

    return {
        "deleted_count": deleted_count,
        "deleted_size_mb": deleted_size_mb,
    }


# ── Recalibration task ──

if settings.celery_enabled:
    @celery_app.task
    def run_recalibration() -> Dict[str, Any]:
        """Weekly batch recalibration from purchase fit feedback."""
        return _run_recalibration_impl()
else:
    def run_recalibration() -> Dict[str, Any]:
        """Synchronous fallback when Celery is disabled."""
        return _run_recalibration_impl()

    run_recalibration.delay = run_recalibration
    run_recalibration.apply_async = lambda *a, **kw: run_recalibration(*a, **kw)


def _run_recalibration_impl() -> Dict[str, Any]:
    """Run the recalibration batch job."""
    try:
        from scripts.recalibrate import recalibrate
        updated = recalibrate(dry_run=False)
        total = sum(len(v) for v in updated.values())
        logger.info("Recalibration complete: %d offset(s) in %d group(s)", total, len(updated))
        return {"groups_updated": len(updated), "offsets_updated": total}
    except Exception as e:
        logger.error("Recalibration failed: %s", e)
        return {"error": str(e)}
