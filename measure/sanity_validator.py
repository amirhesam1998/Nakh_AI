"""
Sanity validation engine for body measurements.

Checks measurements against anthropometric ranges and body-proportion ratios.
Produces warnings but does NOT clamp or modify values.
"""
from typing import Dict, List, Tuple

import numpy as np

# ── Absolute anthropometric ranges by body model ──
SANITY_RANGES: Dict[str, Dict[str, Tuple[float, float]]] = {
    "adult": {
        "chest_circum_cm":    (70, 145),
        "waist_circum_cm":    (55, 135),
        "hip_circum_cm":      (75, 145),
        "neck_circum_cm":     (28, 55),
        "upperarm_circum_cm": (18, 55),
        "thigh_circum_cm":    (35, 85),
        "calf_circum_cm":     (25, 55),
        "sleeve_len_cm":      (45, 90),
        "pants_outseam_cm":   (80, 130),
        "shoulder_width_cm":  (30, 60),
    },
    "teen": {
        "chest_circum_cm":    (55, 115),
        "waist_circum_cm":    (45, 100),
        "hip_circum_cm":      (60, 120),
        "neck_circum_cm":     (24, 45),
        "upperarm_circum_cm": (15, 45),
        "thigh_circum_cm":    (30, 70),
        "calf_circum_cm":     (22, 48),
        "sleeve_len_cm":      (38, 78),
        "pants_outseam_cm":   (70, 115),
        "shoulder_width_cm":  (28, 52),
    },
    "child": {
        "chest_circum_cm":    (45, 90),
        "waist_circum_cm":    (40, 80),
        "hip_circum_cm":      (48, 95),
        "neck_circum_cm":     (20, 38),
        "upperarm_circum_cm": (12, 35),
        "thigh_circum_cm":    (22, 55),
        "calf_circum_cm":     (18, 40),
        "sleeve_len_cm":      (25, 60),
        "pants_outseam_cm":   (40, 95),
        "shoulder_width_cm":  (20, 42),
    },
}

# ── Body-proportion ratio checks ──
RATIO_CHECKS = {
    "waist_hip": {
        "num": "waist_circum_cm", "den": "hip_circum_cm",
        "range": (0.58, 1.08),
    },
    "arm_chest": {
        "num": "upperarm_circum_cm", "den": "chest_circum_cm",
        "range": (0.18, 0.52),
    },
    "thigh_hip": {
        "num": "thigh_circum_cm", "den": "hip_circum_cm",
        "range": (0.42, 0.95),
    },
    "sleeve_height": {
        "num": "sleeve_len_cm", "den": "user_height_cm",
        "range": (0.28, 0.42),
    },
    "neck_chest": {
        "num": "neck_circum_cm", "den": "chest_circum_cm",
        "range": (0.30, 0.55),
    },
}


def validate_measurements(
    measurements: dict,
    body_model: str = "adult",
) -> Dict[str, List[str]]:
    """Run sanity checks on all measurements.

    Returns a dict mapping measurement_key → list of warning strings.
    Keys with no warnings are omitted.
    """
    warnings: Dict[str, List[str]] = {}
    ranges = SANITY_RANGES.get(body_model, SANITY_RANGES["adult"])

    # 1) Absolute range checks
    for key, (lo, hi) in ranges.items():
        val = measurements.get(key)
        if val is None or not isinstance(val, (int, float)):
            continue
        if not np.isfinite(val):
            warnings.setdefault(key, []).append("measurement is NaN/Inf")
            continue
        if val < lo:
            warnings.setdefault(key, []).append(
                f"value {val:.1f} below expected minimum {lo}"
            )
        elif val > hi:
            warnings.setdefault(key, []).append(
                f"value {val:.1f} above expected maximum {hi}"
            )

    # 2) Ratio checks
    for check_name, spec in RATIO_CHECKS.items():
        num_val = measurements.get(spec["num"])
        den_val = measurements.get(spec["den"])
        if (num_val is None or den_val is None or
                not isinstance(num_val, (int, float)) or
                not isinstance(den_val, (int, float))):
            continue
        if den_val < 1e-6:
            continue
        ratio = num_val / den_val
        lo, hi = spec["range"]
        if ratio < lo or ratio > hi:
            warnings.setdefault(spec["num"], []).append(
                f"{check_name} ratio {ratio:.2f} outside [{lo}, {hi}]"
            )

    return warnings


def collect_global_warnings(
    per_key_warnings: Dict[str, List[str]],
) -> List[str]:
    """Flatten per-key warnings into a global warning list."""
    out = []
    for key, msgs in per_key_warnings.items():
        for msg in msgs:
            out.append(f"{key}: {msg}")
    return out
