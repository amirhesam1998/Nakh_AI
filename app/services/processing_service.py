"""
Processing service for PARE-based body measurement.
"""
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from app.config import settings
from app.database import RedisStorage

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

    # Preserve non-numeric fields
    for k in ("gender",):
        for d in measure_list:
            if k in d:
                avg[k] = d[k]
                break

    return avg


class ProcessingService:
    """Service for PARE processing operations."""

    def __init__(self, media_root: Optional[Path] = None):
        self.media_root = media_root or settings.media_path

    async def process_upload(
        self,
        storage: RedisStorage,
        upload_id: str,
        user_height_cm: float,
        user_weight_kg: float,
        gender: str,
    ) -> Dict[str, Any]:
        """
        Process an upload using PARE.

        Args:
            storage: Redis storage instance
            upload_id: Upload ID
            user_height_cm: User height in cm
            user_weight_kg: User weight in kg
            gender: User gender

        Returns:
            Processing results dictionary
        """
        logger.info(f"Starting PARE processing for upload {upload_id}")

        # Get upload from Redis
        upload = await storage.get_upload(upload_id)

        if not upload:
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

        try:
            # Import processing utilities
            from measure.body_measurement import BodyMeasurement as BM
            from measure.image_enhancement import ImageToolkit
            from measure.make_video import MakeVideo
            from measure.save_smpl_frames import SMPLExtractor
            from measure.body_silhouette import BodySilhouetteRenderer
            from measure.body_mannequin import BodyMannequinRenderer
            from measure.three_mannequin import build_mannequin_config

            # Calculate width_scale from BMI
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

                image_path = self.media_root / image_field
                if not image_path.exists():
                    errors.append(f"Image not found: {image_field}")
                    continue

                try:
                    result_data = tk.run_file(
                        src_path=image_path,
                        out_dir=self.media_root / "processed",
                        quality=95,
                    )
                    out_path = Path(result_data["out"])
                    processed_paths.append(out_path)
                    results["processed_urls"].append(
                        f"/media/processed/{out_path.name}"
                    )
                except Exception as e:
                    logger.error(f"Image processing error: {e}")
                    errors.append(f"Image processing: {e}")

            # 2) Create video from processed images
            video_out_path = None
            if len(processed_paths) >= 3:
                try:
                    videos_dir = self.media_root / "videos"
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
                    errors.append(f"Video creation: {e}")
            else:
                errors.append("At least 3 processed images required for video")

            # 3) Run PARE and extract measurements
            if results["video_url"] and video_out_path and not errors:
                results = await self._run_pare_processing(
                    results,
                    errors,
                    video_out_path,
                    upload_id,
                    user_height_cm,
                    width_scale,
                    gender,
                    BM,
                    SMPLExtractor,
                    BodySilhouetteRenderer,
                    BodyMannequinRenderer,
                    build_mannequin_config,
                )

        except ImportError as e:
            logger.error(f"Import error: {e}")
            errors.append(f"Processing modules not available: {e}")
        except Exception as e:
            logger.error(f"Processing error: {e}")
            errors.append(f"Processing error: {e}")

        # Update upload record in Redis
        await storage.update_upload(
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

    async def _run_pare_processing(
        self,
        results: Dict[str, Any],
        errors: List[str],
        video_path: Path,
        upload_id: str,
        user_height_cm: float,
        width_scale: float,
        gender: str,
        BM,
        SMPLExtractor,
        BodySilhouetteRenderer,
        BodyMannequinRenderer,
        build_mannequin_config,
    ) -> Dict[str, Any]:
        """Run PARE model and extract measurements."""
        try:
            # Find PARE script
            pare_root = Path(__file__).resolve().parent.parent.parent / "measure" / "PARE"
            pare_script = pare_root / "scripts" / "demo.py"

            if not pare_script.exists():
                errors.append(f"PARE script not found: {pare_script}")
                return results

            output_folder = self.media_root / "AI_Processing" / "pre"
            output_folder.mkdir(parents=True, exist_ok=True)

            # Find checkpoint files
            ckpt_dir = pare_root / "scripts" / "data" / "pare" / "checkpoints"
            cfg_path = ckpt_dir / "pare_w_3dpw_config.yaml"
            ckpt_path = ckpt_dir / "pare_w_3dpw_checkpoint.ckpt"

            if not cfg_path.exists() or not ckpt_path.exists():
                errors.append("PARE checkpoints not found")
                return results

            # Run PARE
            command = [
                sys.executable,
                str(pare_script),
                "--mode", "video",
                "--vid_file", str(video_path),
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

            if result.returncode != 0:
                errors.append(f"PARE error: {result.stderr.strip()}")
                return results

            # Find and process PKL output
            pkl_path = next(output_folder.rglob("*.pkl"), None)
            if not pkl_path:
                errors.append("PARE output not found")
                return results

            # Extract SMPL frames
            extractor = SMPLExtractor(str(pkl_path))
            npz_files = extractor.extract_and_save()

            # Measure each view
            label_by_name = {"front": "Front", "tpose": "T-Pose", "side": "Side"}
            per_view_results = []

            for fpath in npz_files:
                fpath = Path(fpath)
                rel = fpath.relative_to(self.media_root)
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
                    errors.append(f"Measurement error ({fpath.name}): {e}")

            # Calculate average measurements
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
                body_models_dir = self.media_root / "body_models"
                body_models_dir.mkdir(parents=True, exist_ok=True)

                try:
                    silhouette_renderer = BodySilhouetteRenderer(out_dir=body_models_dir)
                    silhouette_path = silhouette_renderer.render(
                        avg_res, file_name=f"silhouette_{upload_id}.png"
                    )
                    results["silhouette_url"] = (
                        f"/media/body_models/{Path(silhouette_path).name}"
                    )
                except Exception as e:
                    errors.append(f"Silhouette: {e}")

                try:
                    mannequin_renderer = BodyMannequinRenderer(out_dir=body_models_dir)
                    mannequin_path = mannequin_renderer.render(
                        avg_res, file_name=f"mannequin_{upload_id}.png"
                    )
                    results["mannequin_url"] = (
                        f"/media/body_models/{Path(mannequin_path).name}"
                    )
                except Exception as e:
                    errors.append(f"Mannequin: {e}")

                try:
                    results["three_cfg"] = build_mannequin_config(avg_res)
                except Exception as e:
                    errors.append(f"3D config: {e}")

        except subprocess.TimeoutExpired:
            errors.append("PARE timed out (10 minutes)")
        except Exception as e:
            logger.error(f"PARE processing error: {e}")
            errors.append(f"PARE: {e}")

        return results
