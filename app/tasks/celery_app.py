"""
Celery application configuration.
"""
from celery import Celery

from app.config import settings

# Create Celery app
celery_app = Celery(
    "nakh",
    broker=settings.celery_broker_url if settings.celery_enabled else "memory://",
    backend=settings.celery_result_backend if settings.celery_enabled else "cache+memory://",
    include=[
        "app.tasks.processing",
        "app.tasks.cleanup",
    ],
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.celery_task_time_limit,
    worker_prefetch_multiplier=1,  # Process one task at a time (for GPU tasks)
)

# Eager mode when Celery is disabled (run tasks synchronously)
if not settings.celery_enabled:
    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )

# Beat schedule for periodic tasks
if settings.celery_enabled:
    celery_app.conf.beat_schedule = {
        "cleanup-old-media-weekly": {
            "task": "app.tasks.cleanup.cleanup_old_media_files",
            "schedule": 60 * 60 * 24 * 7,  # Weekly
            "args": (7,),  # Delete files older than 7 days
        },
        "recalibrate-weekly": {
            "task": "app.tasks.cleanup.run_recalibration",
            "schedule": 60 * 60 * 24 * 7,  # Weekly
        },
    }
