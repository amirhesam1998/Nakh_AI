"""
Per-measurement confidence score computation.
"""
from typing import Dict, List

import numpy as np

# Maps each measurement to the views most relevant for its accuracy.
SOURCE_MAP = {
    "chest_circum_cm":    ["front_a", "side"],
    "waist_circum_cm":    ["front_a", "side"],
    "hip_circum_cm":      ["back_a", "side"],
    "neck_circum_cm":     ["front_a", "back_a"],
    "upperarm_circum_cm": ["front_a", "front_t"],
    "thigh_circum_cm":    ["front_a", "side"],
    "calf_circum_cm":     ["front_a", "side"],
    "sleeve_len_cm":      ["front_t"],
    "pants_outseam_cm":   ["front_a"],
    "top_len_cm":         ["front_a"],
    "gown_len_cm":        ["front_a"],
    "shoulder_width_cm":  ["front_t"],
}


def compute_confidence(
    measurement_key: str,
    quality_scores: Dict[str, float],
    sanity_warnings: List[str],
    slice_stability: float = 0.85,
) -> float:
    """Compute a confidence score in [0, 1] for one measurement.

    Parameters
    ----------
    measurement_key : str
    quality_scores : dict
        Per-view quality scores {"front_a": 0.91, ...}.
    sanity_warnings : list[str]
        Warnings produced by the sanity validator for this key.
    slice_stability : float
        How stable the cross-section slices were (0–1).
        Default 0.85 when not computed (e.g. length measurements).
    """
    # Component 1: image quality (mean of relevant views)
    relevant = SOURCE_MAP.get(measurement_key, list(quality_scores.keys()))
    view_quals = [quality_scores.get(v, 0.5) for v in relevant]
    quality_component = float(np.mean(view_quals)) if view_quals else 0.5

    # Component 2: slice stability
    stability_component = float(slice_stability)

    # Component 3: sanity pass
    if not sanity_warnings:
        sanity_component = 1.0
    else:
        sanity_component = max(0.0, 1.0 - 0.25 * len(sanity_warnings))

    confidence = (
        0.35 * quality_component
        + 0.35 * stability_component
        + 0.30 * sanity_component
    )
    return float(np.clip(confidence, 0.0, 1.0))


def compute_all_confidences(
    measurements: dict,
    quality_scores: Dict[str, float],
    per_key_warnings: Dict[str, List[str]],
) -> Dict[str, float]:
    """Compute confidence for every measurement key.

    Returns dict mapping measurement_key → confidence float.
    """
    confidences = {}
    for key, val in measurements.items():
        if not isinstance(val, (int, float)):
            continue
        if not np.isfinite(val):
            continue
        if not key.endswith("_cm"):
            continue
        warnings = per_key_warnings.get(key, [])
        confidences[key] = compute_confidence(
            key, quality_scores, warnings,
        )
    return confidences
