"""
Image validation checks run BEFORE any AI model.

Each check returns warnings (soft) or rejections (hard).
Uses MediaPipe Tasks API (0.10.x+) for pose detection.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Path to the downloaded PoseLandmarker model
_POSE_MODEL_PATH = Path(__file__).resolve().parent / "data" / "pose_landmarker_lite.task"


@dataclass
class ValidationResult:
    """Result of validating a single image."""
    passed: bool = True
    warnings: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    blur_score: float = 0.0
    brightness: float = 128.0
    body_ratio: float = 0.0
    mean_visibility: float = 0.0
    pose_valid: bool = True

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    def reject(self, msg: str):
        self.rejections.append(msg)
        self.passed = False


def _create_pose_landmarker():
    """Create a PoseLandmarker using the Tasks API."""
    import mediapipe as mp_lib
    from mediapipe.tasks.python import BaseOptions, vision

    if not _POSE_MODEL_PATH.exists():
        logger.warning(f"Pose model not found at {_POSE_MODEL_PATH}")
        return None

    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(_POSE_MODEL_PATH)),
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return vision.PoseLandmarker.create_from_options(options)


def validate_image(
    image_path: str,
    expected_pose: str = "front_a",
    landmarker=None,
) -> ValidationResult:
    """Run all validation checks on a single image.

    Parameters
    ----------
    image_path : str
        Path to the image file.
    expected_pose : str
        One of "front_a", "side", "back_a", "front_t".
    landmarker : PoseLandmarker or None
        Reusable instance. Created if None.
    """
    result = ValidationResult()

    img = cv2.imread(str(image_path))
    if img is None:
        result.reject("cannot read image file")
        return result

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # --- Blur detection ---
    result.blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if result.blur_score < 50:
        result.reject("image too blurry")
    elif result.blur_score < 100:
        result.add_warning("image may be blurry")

    # --- Lighting check ---
    result.brightness = float(np.mean(gray))
    if result.brightness < 40:
        result.reject("image too dark")
    elif result.brightness > 240:
        result.add_warning("image overexposed")

    # --- MediaPipe body visibility + framing + pose ---
    import mediapipe as mp_lib

    close_landmarker = False
    if landmarker is None:
        landmarker = _create_pose_landmarker()
        close_landmarker = True

    if landmarker is None:
        # No model available — skip pose checks, return basic results
        result.mean_visibility = 0.5
        result.body_ratio = 0.75
        return result

    try:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp_lib.Image(
            image_format=mp_lib.ImageFormat.SRGB,
            data=rgb,
        )
        mp_result = landmarker.detect(mp_image)

        if not mp_result.pose_landmarks or len(mp_result.pose_landmarks) == 0:
            result.reject("no person detected")
            return result

        lm = mp_result.pose_landmarks[0]  # First (only) pose
        visibilities = [l.visibility for l in lm]
        result.mean_visibility = float(np.mean(visibilities))

        # Key landmark visibility (MediaPipe Tasks uses same 33 landmark indices)
        key_indices = {
            "nose": 0,
            "left_heel": 29, "right_heel": 30,
            "left_wrist": 15, "right_wrist": 16,
            "left_shoulder": 11, "right_shoulder": 12,
            "left_hip": 23, "right_hip": 24,
        }
        # Only warn about low visibility for landmarks expected in this pose
        skip_in_pose = {
            "side": {"left_wrist", "right_wrist", "left_heel", "right_heel"},
            "back_a": {"nose", "left_wrist", "right_wrist"},
        }
        skip_set = skip_in_pose.get(expected_pose, set())
        for name, idx in key_indices.items():
            if name in skip_set:
                continue
            if visibilities[idx] < 0.2:
                result.add_warning(f"{name} not clearly visible")

        # Head/feet check — skip head check for back pose (nose not visible)
        if expected_pose != "back_a" and visibilities[0] < 0.2:
            result.reject("head not visible — may be cropped")
        if visibilities[29] < 0.2 and visibilities[30] < 0.2:
            result.reject("feet not visible — may be cropped")

        # Body ratio (framing)
        nose_y = lm[0].y
        heel_y = max(lm[29].y, lm[30].y)
        result.body_ratio = float(np.clip((heel_y - nose_y) * 1.08, 0.0, 1.0))

        if result.body_ratio < 0.50:
            result.add_warning("stand closer to camera")
        elif result.body_ratio > 0.95:
            result.add_warning("stand further from camera")

        # Pose template validation
        result.pose_valid = _check_pose_template(lm, expected_pose, w, h)
        if not result.pose_valid:
            result.add_warning(f"pose does not match expected {expected_pose}")

    finally:
        if close_landmarker:
            landmarker.close()

    return result


def _check_pose_template(lm, expected_pose: str, w: int, h: int) -> bool:
    """Check if detected landmarks match the expected pose template."""
    def px(idx):
        return (lm[idx].x * w, lm[idx].y * h)

    def vis(idx):
        return lm[idx].visibility

    try:
        if expected_pose == "front_a":
            ls, rs = px(11), px(12)
            lh, rh = px(23), px(24)
            lw, rw = px(15), px(16)
            shoulder_dy = abs(ls[1] - rs[1]) / h
            hip_dy = abs(lh[1] - rh[1]) / h
            wrist_ok = (lw[1] > ls[1] and rw[1] > rs[1] and
                        lw[1] < lh[1] and rw[1] < rh[1])
            return shoulder_dy < 0.12 and hip_dy < 0.12 and wrist_ok

        elif expected_pose == "side":
            # MediaPipe often detects both shoulders even in true side
            # photos, so this check is very lenient — only fail if the
            # pose is clearly frontal (both shoulders high-vis + symmetric)
            ls_vis, rs_vis = vis(11), vis(12)
            both_very_visible = min(ls_vis, rs_vis) > 0.9
            very_symmetric = abs(ls_vis - rs_vis) < 0.05
            return not (both_very_visible and very_symmetric)

        elif expected_pose == "back_a":
            # MediaPipe can hallucinate nose landmark from behind;
            # only fail if nose is clearly, confidently detected
            return vis(0) < 0.95

        elif expected_pose == "front_t":
            ls, rs = px(11), px(12)
            lw, rw = px(15), px(16)
            shoulder_width = abs(ls[0] - rs[0])
            wrist_span = abs(lw[0] - rw[0])
            wrist_at_shoulder_y = (
                abs(lw[1] - ls[1]) / h < 0.18 and
                abs(rw[1] - rs[1]) / h < 0.18
            )
            wide_arms = wrist_span > 1.5 * shoulder_width
            return wrist_at_shoulder_y and wide_arms

    except (IndexError, AttributeError):
        pass

    return True  # default: pass if we can't check


def validate_all_images(
    image_paths: dict,
) -> dict:
    """Validate all 4 pose images.

    Parameters
    ----------
    image_paths : dict
        Mapping pose_name -> file path.

    Returns
    -------
    dict mapping pose_name -> ValidationResult
    """
    landmarker = _create_pose_landmarker()

    results = {}
    try:
        for pose_name, path in image_paths.items():
            results[pose_name] = validate_image(
                str(path), expected_pose=pose_name, landmarker=landmarker,
            )
    finally:
        if landmarker is not None:
            landmarker.close()

    return results
