"""
PARE processing Celery task.
"""
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import redis

from app.config import settings

logger = logging.getLogger(__name__)


def _average_measurements_dict(measure_list: List[Dict]) -> Dict[str, Any]:
    """Average numeric measurements across multiple views."""
    if not measure_list:
        return {}

    keys = set().union(*(d.keys() for d in measure_list))
    avg = {}

    for k in keys:
        vals = []
        for d in measure_list:
            v = d.get(k, None)
            if isinstance(v, (int, float)) and np.isfinite(v):
                vals.append(float(v))
        if vals:
            avg[k] = float(np.mean(vals))

    for k in ("gender",):
        for d in measure_list:
            if k in d:
                avg[k] = d[k]
                break

    return avg


def _get_sync_redis() -> redis.Redis:
    """Get synchronous Redis client for Celery tasks."""
    return redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


def _get_upload(r: redis.Redis, upload_id: str) -> Dict[str, Any] | None:
    """Get upload from Redis."""
    data = r.get(f"upload:{upload_id}")
    return json.loads(data) if data else None


def _update_upload(r: redis.Redis, upload_id: str, updates: Dict[str, Any]) -> None:
    """Update upload in Redis."""
    data = r.get(f"upload:{upload_id}")
    if not data:
        return

    upload = json.loads(data)
    upload.update(updates)

    # Preserve TTL
    ttl = r.ttl(f"upload:{upload_id}")
    if ttl > 0:
        r.set(f"upload:{upload_id}", json.dumps(upload), ex=ttl)
    else:
        r.set(f"upload:{upload_id}", json.dumps(upload))


# Conditional import based on Celery availability
if settings.celery_enabled:
    from app.tasks.celery_app import celery_app

    @celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
    def process_upload_pare(
        self,
        upload_id: str,
        user_height_cm: float,
        user_weight_kg: float,
        gender: str,
    ) -> Dict[str, Any]:
        """Background task to process uploaded photos using PARE."""
        return _process_upload_pare_impl(
            self, upload_id, user_height_cm, user_weight_kg, gender
        )
else:
    # Fallback for when Celery is disabled
    class MockTask:
        def retry(self, *args, **kwargs):
            raise kwargs.get("exc", Exception("Task retry"))

    def process_upload_pare(
        upload_id: str,
        user_height_cm: float,
        user_weight_kg: float,
        gender: str,
    ) -> Dict[str, Any]:
        """Synchronous fallback when Celery is disabled."""
        return _process_upload_pare_impl(
            MockTask(), upload_id, user_height_cm, user_weight_kg, gender
        )

    # Add delay method for compatibility
    process_upload_pare.delay = process_upload_pare
    process_upload_pare.apply_async = lambda *a, **kw: process_upload_pare(*a, **kw)


def _process_upload_pare_impl(
    task,
    upload_id: str,
    user_height_cm: float,
    user_weight_kg: float,
    gender: str,
) -> Dict[str, Any]:
    """
    Implementation of PARE processing task.

    Args:
        task: Celery task instance (or mock)
        upload_id: ID of the upload
        user_height_cm: User's height in cm
        user_weight_kg: User's weight in kg
        gender: User's gender ('male' or 'female')

    Returns:
        Dictionary with processing results
    """
    logger.info(f"Starting PARE processing for upload {upload_id}")

    # Use sync Redis for Celery tasks
    r = _get_sync_redis()

    upload = _get_upload(r, upload_id)
    if not upload:
        logger.error(f"Upload {upload_id} not found")
        return {"error": f"Upload {upload_id} not found", "status": "failed"}

    errors = []
    results = {
        "upload_id": upload_id,
        "status": "processing",
        "processed_urls": [],
        "video_url": None,
        "npz_urls": [],
        "measurements": [],
        "silhouette_url": None,
        "mannequin_url": None,
        "three_cfg": None,
        "errors": [],
    }

    media_root = settings.media_path

    try:
        # Import processing utilities
        from measure.body_measurement import BodyMeasurement as BM
        from measure.image_enhancement import ImageToolkit
        from measure.make_video import MakeVideo
        from measure.save_smpl_frames import SMPLExtractor
        from measure.body_silhouette import BodySilhouetteRenderer
        from measure.body_mannequin import BodyMannequinRenderer
        from measure.three_mannequin import build_mannequin_config

        # Calculate width_scale
        width_scale, bmi = BM.width_scale_from_weight_height(
            user_weight_kg, user_height_cm
        )
        results["width_scale"] = width_scale
        results["bmi"] = bmi

        # 1) Process images
        tk = ImageToolkit()
        processed_paths = []

        for image_field in [upload.get("image1"), upload.get("image2"), upload.get("image3")]:
            if not image_field:
                continue

            image_path = media_root / image_field
            try:
                result_data = tk.run_file(
                    src_path=image_path,
                    out_dir=media_root / "processed",
                    quality=95,
                )
                out_path = Path(result_data["out"])
                processed_paths.append(out_path)
                results["processed_urls"].append(
                    f"/media/processed/{out_path.name}"
                )
            except Exception as e:
                logger.error(f"Image processing error: {e}")
                errors.append(str(e))

        # 2) Create video
        video_out_path = None
        if len(processed_paths) >= 3:
            try:
                videos_dir = media_root / "videos"
                videos_dir.mkdir(parents=True, exist_ok=True)
                out_file = videos_dir / f"upload_{upload_id}.mp4"

                mv = MakeVideo(
                    img_dir=None,
                    output=out_file,
                    fps=1,
                    resize_mode="fit",
                    overwrite=True,
                )
                video_out_path, frames = mv.make_from_images(processed_paths)
                results["video_url"] = f"/media/videos/{video_out_path.name}"
            except Exception as e:
                logger.error(f"Video creation error: {e}")
                errors.append(f"video: {e}")
        else:
            errors.append("At least 3 processed images required")

        # 3) Run PARE
        if video_out_path and not errors:
            pare_root = Path(__file__).resolve().parent.parent.parent / "measure" / "PARE"
            pare_script = pare_root / "scripts" / "demo.py"

            if pare_script.exists():
                output_folder = media_root / "AI_Processing" / "pre"
                output_folder.mkdir(parents=True, exist_ok=True)

                ckpt_dir = pare_root / "scripts" / "data" / "pare" / "checkpoints"
                cfg_path = ckpt_dir / "pare_w_3dpw_config.yaml"
                ckpt_path = ckpt_dir / "pare_w_3dpw_checkpoint.ckpt"

                if cfg_path.exists() and ckpt_path.exists():
                    command = [
                        sys.executable,
                        str(pare_script),
                        "--mode", "video",
                        "--vid_file", str(video_out_path),
                        "--output_folder", str(output_folder),
                        "--no_render",
                        "--cfg", str(cfg_path),
                        "--ckpt", str(ckpt_path),
                    ]

                    logger.info(f"Running PARE: {' '.join(command)}")
                    result = subprocess.run(
                        command,
                        cwd=str(pare_script.parent),
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )

                    if result.returncode == 0:
                        # Extract and measure
                        pkl_path = next(output_folder.rglob("*.pkl"), None)
                        if pkl_path:
                            extractor = SMPLExtractor(str(pkl_path))
                            npz_files = extractor.extract_and_save()

                            label_by_name = {
                                "front": "Front",
                                "tpose": "T-Pose",
                                "side": "Side",
                            }
                            per_view_results = []

                            for fpath in npz_files:
                                fpath = Path(fpath)
                                rel = fpath.relative_to(media_root)
                                url = f"/media/{rel.as_posix()}"
                                results["npz_urls"].append(url)

                                try:
                                    res = BM.measure_from_npz(
                                        npz_path=str(fpath),
                                        user_height_cm=user_height_cm,
                                        gender=gender,
                                        width_scale=width_scale,
                                    )
                                    per_view_results.append(res)
                                    fname = fpath.name.lower()
                                    label = next(
                                        (v for k, v in label_by_name.items() if k in fname),
                                        fpath.stem,
                                    )
                                    results["measurements"].append({
                                        "label": label,
                                        "file_url": url,
                                        "results": res,
                                        "pretty": BM.pretty_farsi(res),
                                    })
                                except Exception as e:
                                    errors.append(f"measure({fpath.name}): {e}")

                            # Average measurements
                            if per_view_results:
                                avg_res = _average_measurements_dict(per_view_results)
                                avg_res.update({
                                    "user_height_cm": user_height_cm,
                                    "width_scale": width_scale,
                                    "gender": gender,
                                })
                                results["measurements"].append({
                                    "label": "Average",
                                    "file_url": None,
                                    "results": avg_res,
                                    "pretty": BM.pretty_farsi(avg_res),
                                })

                                # Generate visualizations
                                body_models_dir = media_root / "body_models"
                                body_models_dir.mkdir(parents=True, exist_ok=True)

                                try:
                                    renderer = BodySilhouetteRenderer(out_dir=body_models_dir)
                                    path = renderer.render(
                                        avg_res, file_name=f"silhouette_{upload_id}.png"
                                    )
                                    results["silhouette_url"] = (
                                        f"/media/body_models/{Path(path).name}"
                                    )
                                except Exception as e:
                                    errors.append(f"silhouette: {e}")

                                try:
                                    renderer = BodyMannequinRenderer(out_dir=body_models_dir)
                                    path = renderer.render(
                                        avg_res, file_name=f"mannequin_{upload_id}.png"
                                    )
                                    results["mannequin_url"] = (
                                        f"/media/body_models/{Path(path).name}"
                                    )
                                except Exception as e:
                                    errors.append(f"mannequin: {e}")

                                try:
                                    results["three_cfg"] = build_mannequin_config(avg_res)
                                except Exception as e:
                                    errors.append(f"3D-config: {e}")
                        else:
                            errors.append("PKL output not found")
                    else:
                        errors.append(f"PARE error: {result.stderr.strip()}")
                else:
                    errors.append("PARE checkpoints not found")
            else:
                errors.append("PARE script not found")

    except subprocess.TimeoutExpired:
        errors.append("PARE timed out (10 minutes)")
    except Exception as e:
        logger.error(f"PARE error: {e}")
        errors.append(f"PARE: {e}")
        # Retry on GPU/memory errors
        if "CUDA" in str(e) or "memory" in str(e).lower():
            if hasattr(task, "retry"):
                raise task.retry(exc=e)

    # Update upload in Redis
    _update_upload(
        r,
        upload_id,
        {
            "is_processed": True,
            "processed_at": datetime.utcnow().isoformat(),
            "processing_results": json.dumps(results),
        },
    )

    results["errors"] = errors
    results["status"] = "completed" if not errors else "completed_with_errors"

    logger.info(f"PARE processing completed for upload {upload_id}")
    return results
