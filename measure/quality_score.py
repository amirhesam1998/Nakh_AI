"""
Per-view image quality scoring for multi-view beta fusion.
"""
import numpy as np


def compute_quality_score(
    mp_visibility: float,
    blur_score: float,
    body_ratio: float,
    pose_valid: bool,
    pare_succeeded: bool,
) -> float:
    """Compute a quality score in [0, 1] for a single view.

    Parameters
    ----------
    mp_visibility : float
        Mean MediaPipe landmark visibility for this image [0, 1].
    blur_score : float
        Laplacian variance of the grayscale image (higher = sharper).
    body_ratio : float
        body_pixel_height / image_height [0, 1].
    pose_valid : bool
        Whether the detected pose matches the expected template.
    pare_succeeded : bool
        Whether PARE successfully detected a person.
    """
    if not pare_succeeded:
        return 0.0

    quality = float(np.clip(mp_visibility, 0.0, 1.0))

    if blur_score < 100:
        quality *= 0.5

    if body_ratio < 0.50 or body_ratio > 0.95:
        quality *= 0.7

    if not pose_valid:
        quality *= 0.4

    return float(np.clip(quality, 0.0, 1.0))


def compute_quality_from_landmarks(landmarks) -> dict:
    """Extract quality signals from MediaPipe pose landmarks.

    Parameters
    ----------
    landmarks : mediapipe NormalizedLandmarkList or None
        The 33 pose landmarks from MediaPipe.

    Returns
    -------
    dict with keys: mean_visibility, body_ratio, pose_valid
    """
    if landmarks is None:
        return {
            "mean_visibility": 0.0,
            "body_ratio": 0.0,
            "pose_valid": False,
        }

    visibilities = [lm.visibility for lm in landmarks.landmark]
    mean_vis = float(np.mean(visibilities))

    # Body ratio: nose-to-heel Y range
    nose_y = landmarks.landmark[0].y
    left_heel_y = landmarks.landmark[29].y
    right_heel_y = landmarks.landmark[30].y
    body_ratio = max(left_heel_y, right_heel_y) - nose_y
    body_ratio = float(np.clip(body_ratio * 1.08, 0.0, 1.0))

    # Pose validity: basic check that key landmarks are visible
    key_indices = [0, 11, 12, 23, 24, 15, 16, 29, 30]  # nose, shoulders, hips, wrists, heels
    key_vis = [visibilities[i] for i in key_indices]
    pose_valid = all(v > 0.3 for v in key_vis)

    return {
        "mean_visibility": mean_vis,
        "body_ratio": body_ratio,
        "pose_valid": pose_valid,
    }
