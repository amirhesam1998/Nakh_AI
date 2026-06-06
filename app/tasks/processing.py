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


def _multi_view_fusion(
    per_view_results: List[Dict],
    labels: List[str],
) -> Dict[str, Any]:
    """Multi-view measurement fusion per the pose optimization spec.

    Uses preferred source poses for each measurement:
    - Shoulder Width:      Front T-Pose
    - Chest Circumference: Front A + Side (average)
    - Waist Circumference: Front A + Side (average)
    - Hip Circumference:   Back A + Side (average)
    - Arm Length:          Front T-Pose
    - Torso Width:         Front A-Pose
    - Back Width:          Back A-Pose
    - Posture/Body Depth:  Side
    - Other measurements:  average across all views
    """
    if not per_view_results:
        return {}

    # Build label-to-results mapping
    view_map: Dict[str, Dict] = {}
    for label, res in zip(labels, per_view_results):
        label_lower = label.lower()
        if "front" in label_lower and "t" in label_lower:
            view_map["front_t"] = res
        elif "front" in label_lower and "a" in label_lower:
            view_map["front_a"] = res
        elif "back" in label_lower:
            view_map["back_a"] = res
        elif "side" in label_lower:
            view_map["side"] = res
        else:
            # Fallback: try to assign by order if labels don't match
            if "front_a" not in view_map:
                view_map["front_a"] = res
            elif "side" not in view_map:
                view_map["side"] = res
            elif "back_a" not in view_map:
                view_map["back_a"] = res
            elif "front_t" not in view_map:
                view_map["front_t"] = res

    def _get_val(view_key: str, measurement_key: str):
        """Get a measurement value from a specific view."""
        v = view_map.get(view_key, {}).get(measurement_key)
        if v is not None and isinstance(v, (int, float)) and np.isfinite(v):
            return float(v)
        return None

    def _avg_views(view_keys: List[str], measurement_key: str):
        """Average a measurement across multiple views."""
        vals = [_get_val(vk, measurement_key) for vk in view_keys]
        vals = [v for v in vals if v is not None]
        return float(np.mean(vals)) if vals else None

    def _avg_all(measurement_key: str):
        """Average across all available views."""
        vals = []
        for res in per_view_results:
            v = res.get(measurement_key)
            if v is not None and isinstance(v, (int, float)) and np.isfinite(v):
                vals.append(float(v))
        return float(np.mean(vals)) if vals else None

    fused = {}

    # Shoulder width from Front T-Pose (via sleeve_len_cm proxy — PARE gives
    # shoulder-to-wrist distance which is best measured in T-pose)
    # Chest: Front A + Side
    fused["chest_circum_cm"] = _avg_views(["front_a", "side"], "chest_circum_cm")
    # Waist: Front A + Side
    fused["waist_circum_cm"] = _avg_views(["front_a", "side"], "waist_circum_cm")
    # Hip: Back A + Side
    fused["hip_circum_cm"] = _avg_views(["back_a", "side"], "hip_circum_cm")
    # Arm length (sleeve): Front T-Pose preferred
    fused["sleeve_len_cm"] = _get_val("front_t", "sleeve_len_cm") or _avg_all("sleeve_len_cm")
    # Neck: average all
    fused["neck_circum_cm"] = _avg_all("neck_circum_cm")
    # Upper arm: average all
    fused["upperarm_circum_cm"] = _avg_all("upperarm_circum_cm")
    # Thigh: average all
    fused["thigh_circum_cm"] = _avg_all("thigh_circum_cm")
    # Calf: average all
    fused["calf_circum_cm"] = _avg_all("calf_circum_cm")
    # Pants outseam: average all
    fused["pants_outseam_cm"] = _avg_all("pants_outseam_cm")
    # Top length: Front A preferred
    fused["top_len_cm"] = _get_val("front_a", "top_len_cm") or _avg_all("top_len_cm")
    # Gown length: Front A preferred
    fused["gown_len_cm"] = _get_val("front_a", "gown_len_cm") or _avg_all("gown_len_cm")

    # Remove None entries
    fused = {k: v for k, v in fused.items() if v is not None}

    return fused


def _load_metadata(upload_id: str) -> Dict[str, Any] | None:
    """Load upload metadata from JSON file."""
    from app.api.uploads import _load_metadata as _load
    return _load(upload_id)


def _save_metadata(upload_id: str, data: Dict[str, Any]) -> None:
    """Save upload metadata to JSON file."""
    from app.api.uploads import _save_metadata as _save
    _save(upload_id, data)


def classify_body_model(age: int) -> str:
    """Classify user into body-model group based on age.

    Returns 'child', 'teen', or 'adult'.
    """
    if age < 13:
        return "child"
    elif age < 18:
        return "teen"
    else:
        return "adult"


def body_model_circumference_factor(body_model: str) -> float:
    """Scaling factor for circumference estimates by body model.

    Children and teens have different body proportions than adults:
    - Children: smaller head-to-body ratio, narrower shoulders, different
      fat distribution — SMPL/PARE adult priors overestimate circumferences.
    - Teens: closer to adult but still growing — slight correction needed.
    """
    if body_model == "child":
        return 0.85
    elif body_model == "teen":
        return 0.93
    return 1.0


def body_model_length_factor(body_model: str) -> float:
    """Scaling factor for skeletal length estimates by body model.

    Children have proportionally shorter limbs and different leg-to-torso
    ratios compared to the adult SMPL template.
    """
    if body_model == "child":
        return 0.90
    elif body_model == "teen":
        return 0.95
    return 1.0


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
        force: bool = False,
        age: int = 25,
    ) -> Dict[str, Any]:
        """Background task to process uploaded photos using PARE."""
        return _process_upload_pare_impl(
            self, upload_id, user_height_cm, user_weight_kg, gender, force, age=age
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
        force: bool = False,
        age: int = 25,
    ) -> Dict[str, Any]:
        """Synchronous fallback when Celery is disabled."""
        return _process_upload_pare_impl(
            MockTask(), upload_id, user_height_cm, user_weight_kg, gender, force, age=age
        )

    # Add delay method for compatibility
    process_upload_pare.delay = process_upload_pare
    process_upload_pare.apply_async = lambda *a, **kw: process_upload_pare(*a, **kw)


def _subprocess_pare_fallback(
    pare_input_dir: Path,
    output_folder: Path,
    errors: list,
) -> Dict[str, dict]:
    """Run PARE as a subprocess fallback (slow — loads model each time).

    Returns view_data dict or empty dict on failure.
    """
    pare_root = Path(__file__).resolve().parent.parent.parent / "measure" / "PARE"
    pare_script = pare_root / "scripts" / "demo.py"

    if not pare_script.exists():
        errors.append("PARE script not found")
        return {}

    ckpt_dir = pare_root / "scripts" / "data" / "pare" / "checkpoints"
    cfg_path = ckpt_dir / "pare_w_3dpw_config.yaml"
    ckpt_path = ckpt_dir / "pare_w_3dpw_checkpoint.ckpt"

    if not (cfg_path.exists() and ckpt_path.exists()):
        errors.append("PARE checkpoints not found")
        return {}

    command = [
        sys.executable,
        str(pare_script),
        "--mode", "folder",
        "--image_folder", str(pare_input_dir.resolve()),
        "--output_folder", str(output_folder.resolve()),
        "--no_render",
        "--cfg", str(cfg_path),
        "--ckpt", str(ckpt_path),
    ]

    logger.info(f"Running PARE subprocess: {' '.join(command)}")
    try:
        result = subprocess.run(
            command,
            cwd=str(pare_script.parent),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        errors.append("PARE subprocess timed out (10 minutes)")
        return {}

    if result.returncode != 0:
        logger.error(f"PARE subprocess failed (rc={result.returncode}): {result.stderr.strip()}")
        errors.append(f"PARE subprocess error: {result.stderr.strip()[:200]}")
        return {}

    # Parse the packed pkl → extract per-view data
    from measure.save_smpl_frames import SMPLExtractor
    pkl_path = next(output_folder.rglob("*.pkl"), None)
    if not pkl_path:
        errors.append("PARE subprocess produced no pkl output")
        return {}

    extractor = SMPLExtractor(str(pkl_path))
    npz_files = extractor.extract_and_save()

    view_data = {}
    for fpath in npz_files:
        fpath = Path(fpath)
        try:
            data = np.load(str(fpath), allow_pickle=True)
            fname = fpath.stem.lower()
            view_name = next(
                (k for k in ("front_a", "side", "back_a", "front_t") if k in fname),
                fname,
            )
            view_data[view_name] = {
                "vertices": np.asarray(data["vertices"]) if "vertices" in data else None,
                "joints": np.asarray(data["joints"]) if "joints" in data else None,
                "betas": np.asarray(data["betas"]) if "betas" in data else None,
                "pose": np.asarray(data["pose"]) if "pose" in data else None,
            }
        except Exception as e:
            errors.append(f"npz parse({fpath.name}): {e}")

    return view_data


def _process_upload_pare_impl(
    task,
    upload_id: str,
    user_height_cm: float,
    user_weight_kg: float,
    gender: str,
    force: bool = False,
    age: int = 25,
) -> Dict[str, Any]:
    """
    Implementation of PARE processing task.

    Args:
        task: Celery task instance (or mock)
        upload_id: ID of the upload
        user_height_cm: User's height in cm
        user_weight_kg: User's weight in kg
        gender: User's gender ('male' or 'female')
        force: If False, return cached results when the upload has already
            been processed successfully. If True, always re-run PARE.
        age: User's age (used for body model classification)

    Returns:
        Dictionary with processing results
    """
    logger.info(f"Starting PARE processing for upload {upload_id}")

    upload = _load_metadata(upload_id)
    if not upload:
        logger.error(f"Upload {upload_id} not found")
        return {"error": f"Upload {upload_id} not found", "status": "failed"}

    # Idempotency: if PARE already completed for this upload, return the cached
    # result unless the caller explicitly opts into reprocessing.
    if not force and upload.get("is_processed") and upload.get("processing_results"):
        try:
            cached = json.loads(upload["processing_results"])
            if cached.get("status") == "completed":
                logger.info(
                    f"Upload {upload_id} already processed; returning cached results "
                    f"(pass force=True to recompute)."
                )
                return cached
        except (TypeError, ValueError):
            logger.warning(
                f"Cached processing_results for {upload_id} is unreadable; recomputing."
            )

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

    media_root = settings.media_path.resolve()

    try:
        # Import processing utilities
        from measure.body_measurement import BodyMeasurement as BM
        from measure.image_enhancement import ImageToolkit
        from measure.make_video import MakeVideo
        from measure.body_silhouette import BodySilhouetteRenderer
        from measure.body_mannequin import BodyMannequinRenderer
        from measure.three_mannequin import build_mannequin_config

        # Classify body model based on age
        body_model = classify_body_model(age)
        logger.info(f"Upload {upload_id}: age={age}, body_model={body_model}")

        # Calculate width_scale
        width_scale, bmi = BM.width_scale_from_weight_height(
            user_weight_kg, user_height_cm
        )
        results["width_scale"] = width_scale
        results["bmi"] = bmi
        results["body_model"] = body_model
        results["age"] = age

        # 1) Process images (4 poses: front_a, side, back_a, front_t)
        tk = ImageToolkit()
        processed_paths = []
        # image1=Front A-Pose, image2=Side, image3=Back A-Pose, image4=Front T-Pose
        image_fields = [
            upload.get("image1"),
            upload.get("image2"),
            upload.get("image3"),
            upload.get("image4"),
        ]

        for image_field in image_fields:
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

        # 1b) Image validation (blur, lighting, pose, framing)
        pose_names_for_val = ["front_a", "side", "back_a", "front_t"]
        image_validation_results = {}
        validation_quality_scores = {}
        try:
            from measure.image_validator import validate_all_images
            val_paths = {}
            for idx, pp in enumerate(processed_paths):
                if idx < len(pose_names_for_val):
                    val_paths[pose_names_for_val[idx]] = str(pp)
            if val_paths:
                image_validation_results = validate_all_images(val_paths)
                for vname, vr in image_validation_results.items():
                    from measure.quality_score import compute_quality_score
                    validation_quality_scores[vname] = compute_quality_score(
                        mp_visibility=vr.mean_visibility,
                        blur_score=vr.blur_score,
                        body_ratio=vr.body_ratio,
                        pose_valid=vr.pose_valid,
                        pare_succeeded=True,
                    )
                    for w in vr.warnings:
                        logger.info(f"validation({vname}): {w}")
                    for r in vr.rejections:
                        errors.append(f"validation({vname}) REJECTED: {r}")
                logger.info(
                    f"Image validation scores: {validation_quality_scores}"
                )
        except Exception as e:
            logger.warning(f"Image validation failed: {e}")

        # 2) Create video
        video_out_path = None
        if len(processed_paths) >= 4:
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
            errors.append("All 4 processed images required (Front A, Side, Back A, Front T)")

        # 3) Run PARE + consensus mesh pipeline
        if len(processed_paths) >= 4 and not errors:
            output_folder = media_root / "AI_Processing" / upload_id
            output_folder.mkdir(parents=True, exist_ok=True)

            # Copy processed images to a temp folder for PARE
            pare_input_dir = output_folder / "input_images"
            pare_input_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            pose_names = ["front_a", "side", "back_a", "front_t"]
            for idx, img_path in enumerate(processed_paths):
                ext = img_path.suffix
                name = pose_names[idx] if idx < len(pose_names) else f"{idx+1:06d}"
                shutil.copy2(str(img_path), str(pare_input_dir / f"{name}{ext}"))

            # --- Try in-process PARE via ModelRegistry (fast path) ---
            pare_succeeded = False
            try:
                from measure.model_registry import get_registry
                registry = get_registry()

                logger.info(f"Running PARE in-process on {registry.device_name}")
                pkl_paths = registry.run_pare_on_folder(
                    str(pare_input_dir), str(output_folder),
                )
                if pkl_paths:
                    view_data = registry.extract_view_data(pkl_paths)
                    pare_succeeded = bool(view_data)
                    results["processing_device"] = registry.device_name
            except Exception as e:
                logger.warning(f"In-process PARE failed: {e}; falling back to subprocess")
                errors.append(f"in-process PARE: {e}")

            # --- Fallback: subprocess PARE if in-process failed ---
            if not pare_succeeded:
                view_data = _subprocess_pare_fallback(
                    pare_input_dir, output_folder, errors
                )
                results["processing_device"] = "cpu (subprocess)"

            # --- Extract measurements ---
            if view_data:
                from measure.consensus_mesh import fuse_betas

                label_by_name = {
                    "front_a": "Front A-Pose", "side": "Side",
                    "back_a": "Back A-Pose", "front_t": "Front T-Pose",
                }

                all_betas = {}
                quality_scores = {}
                per_view_results = []

                for view_name, vd in view_data.items():
                    label = label_by_name.get(view_name, view_name)

                    if "betas" in vd and vd["betas"] is not None:
                        all_betas[view_name] = vd["betas"]

                    # Quality score from image validation (fallback 0.85)
                    quality_scores[view_name] = validation_quality_scores.get(
                        view_name, 0.85
                    )

                    # Per-view measurement (diagnostic)
                    try:
                        verts = vd.get("vertices")
                        joints = vd.get("joints")
                        if verts is not None and joints is not None:
                            res = BM.measure_pipeline(
                                verts, joints,
                                user_height_cm=user_height_cm,
                                gender=gender,
                                width_scale=width_scale,
                                bmi=bmi,
                            )
                            per_view_results.append(res)
                            results["measurements"].append({
                                "label": label,
                                "file_url": None,
                                "results": res,
                                "pretty": BM.pretty_farsi(res),
                            })
                    except Exception as e:
                        errors.append(f"measure({view_name}): {e}")

                # ── Consensus mesh pipeline ──
                consensus_res = None
                if len(all_betas) >= 2:
                    try:
                        consensus_betas = fuse_betas(all_betas, quality_scores)

                        # Use registry's cached SMPL if available,
                        # otherwise fall back to standalone builder
                        try:
                            registry = get_registry()
                            c_verts, c_joints = registry.build_consensus_mesh(
                                consensus_betas
                            )
                        except Exception:
                            from measure.consensus_mesh import build_consensus_mesh
                            c_verts, c_joints = build_consensus_mesh(
                                consensus_betas, device_str="cpu",
                            )

                        consensus_res = BM.measure_consensus(
                            c_verts, c_joints,
                            user_height_cm=user_height_cm,
                            gender=gender,
                            width_scale=width_scale,
                            bmi=bmi,
                        )
                        logger.info(
                            f"Consensus mesh measurement OK for {upload_id}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Consensus mesh failed for {upload_id}: {e}; "
                            f"falling back to per-view fusion"
                        )
                        errors.append(f"consensus: {e}")

                # Primary result: consensus; fallback: per-view fusion
                if consensus_res is not None:
                    avg_res = consensus_res
                elif per_view_results:
                    view_labels = [
                        m.get("label", "") for m in results["measurements"]
                    ]
                    avg_res = _multi_view_fusion(per_view_results, view_labels)
                    if not avg_res:
                        avg_res = _average_measurements_dict(per_view_results)
                else:
                    avg_res = {}

                if avg_res:
                    avg_res.update({
                        "user_height_cm": user_height_cm,
                        "user_weight_kg": user_weight_kg,
                        "width_scale": width_scale,
                        "gender": gender,
                        "age": age,
                        "body_model": body_model,
                    })

                    # ── Sanity validation + confidence scoring ──
                    per_key_warnings = {}
                    confidences = {}
                    global_warnings = []
                    try:
                        from measure.sanity_validator import (
                            validate_measurements,
                            collect_global_warnings,
                        )
                        from measure.confidence import compute_all_confidences

                        per_key_warnings = validate_measurements(
                            avg_res, body_model=body_model,
                        )
                        global_warnings = collect_global_warnings(
                            per_key_warnings,
                        )
                        confidences = compute_all_confidences(
                            avg_res, quality_scores, per_key_warnings,
                        )
                        logger.info(
                            f"Sanity warnings: {len(global_warnings)}, "
                            f"confidences computed for {len(confidences)} keys"
                        )
                    except Exception as e:
                        logger.warning(f"Sanity/confidence failed: {e}")
                        errors.append(f"sanity/confidence: {e}")

                    # Add image validation warnings to global_warnings
                    for vname, vr in image_validation_results.items():
                        for w in vr.warnings:
                            global_warnings.append(f"{vname}: {w}")

                    # ── Calibration offsets ──
                    try:
                        from measure.calibration import apply_calibration
                        apply_calibration(avg_res, gender=gender, body_model=body_model)
                    except Exception as e:
                        logger.warning(f"Calibration failed: {e}")

                    # ── Learned correction model ──
                    try:
                        from measure.learned_correction import apply_learned_correction
                        apply_learned_correction(avg_res)
                    except Exception as e:
                        logger.warning(f"Learned correction failed: {e}")

                    # ── Silhouette vs mesh comparison ──
                    silhouette_scores = {}
                    try:
                        from measure.silhouette_compare import compare_silhouettes
                        # Use consensus vertices if available
                        sil_verts = (
                            c_verts if consensus_res is not None
                            else None
                        )
                        if sil_verts is not None:
                            img_paths_for_sil = {}
                            for idx, pp in enumerate(processed_paths):
                                if idx < len(pose_names):
                                    img_paths_for_sil[pose_names[idx]] = str(pp)
                            if img_paths_for_sil:
                                silhouette_scores = compare_silhouettes(
                                    sil_verts, img_paths_for_sil,
                                )
                                results["silhouette_scores"] = silhouette_scores
                                logger.info(
                                    f"Silhouette IoU scores: {silhouette_scores}"
                                )
                    except Exception as e:
                        logger.warning(f"Silhouette comparison failed: {e}")

                    results["quality_scores"] = quality_scores
                    results["confidences"] = confidences
                    results["global_warnings"] = global_warnings
                    results["measurements"].append({
                        "label": "Consensus" if consensus_res else "Average",
                        "file_url": None,
                        "results": avg_res,
                        "pretty": BM.pretty_farsi(avg_res),
                    })

                # Generate visualizations
                if avg_res:
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
                errors.append("PARE produced no usable view data")

    except Exception as e:
        logger.error(f"Processing error: {e}")
        errors.append(f"processing: {e}")
        # Retry on GPU/memory errors
        if "CUDA" in str(e) or "memory" in str(e).lower():
            if hasattr(task, "retry"):
                raise task.retry(exc=e)

    results["errors"] = errors
    results["status"] = "completed" if not errors else "completed_with_errors"

    # Include original upload image URLs for the frontend (4 poses)
    results["original_images"] = [
        f"/media/{img}" for img in [
            upload.get('image1'), upload.get('image2'),
            upload.get('image3'), upload.get('image4'),
        ] if img
    ]

    if errors:
        logger.warning(f"PARE processing for {upload_id} completed with errors: {errors}")

    # Update upload metadata on disk
    upload = _load_metadata(upload_id) or {}
    upload.update({
        "is_processed": True,
        "processed_at": datetime.utcnow().isoformat(),
        "processing_status": results["status"],
        "processing_results": json.dumps(results),
    })
    _save_metadata(upload_id, upload)

    # Clean up temporary processing files (keep only original uploads)
    _cleanup_temp_files(upload_id, media_root)

    logger.info(f"PARE processing completed for upload {upload_id}")
    return results


def _cleanup_temp_files(upload_id: str, media_root: Path) -> None:
    """Remove temporary processing artifacts, keeping only original uploads."""
    import shutil

    dirs_to_clean = [
        media_root / "videos",
        media_root / "processed",
        media_root / "body_models",
        media_root / "AI_Processing" / upload_id,
    ]

    for d in dirs_to_clean:
        if d.exists():
            if d.name == upload_id:
                # Remove the per-upload AI_Processing subfolder entirely
                shutil.rmtree(d, ignore_errors=True)
            else:
                # Remove only this upload's files from shared folders
                for f in d.glob(f"*{upload_id}*"):
                    try:
                        f.unlink()
                    except Exception:
                        pass

    logger.info(f"Cleaned up temp files for upload {upload_id}")
