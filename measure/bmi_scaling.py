"""
BMI-based width scaling lookup table.

Replaces the previous single-formula approach ``(bmi/23)^0.15`` with a
gender-aware, per-measurement lookup table derived from ANSUR II (n=4,082),
CAESAR (n=2,400), and Iranian anthropometric standards (ISIRI 7521).

Each circumference measurement has its own *sensitivity* factor so that,
e.g., waist gets full BMI scaling while neck gets only 50%.
"""
from __future__ import annotations

from typing import Optional

# (bmi_upper_bound, scale_male, scale_female)
BMI_SCALE_TABLE: list[tuple[float, float, float]] = [
    (17.5,       0.88, 0.90),
    (20.0,       0.93, 0.94),
    (22.9,       0.97, 0.97),
    (24.9,       1.00, 1.00),
    (27.4,       1.04, 1.03),
    (29.9,       1.07, 1.06),
    (33.9,       1.10, 1.09),
    (37.9,       1.13, 1.11),
    (float("inf"), 1.16, 1.14),
]

BODY_TYPE_ADJUSTMENT: dict[str, dict[str, float]] = {
    "lean":     {"male": -0.03, "female": -0.02},
    "average":  {"male":  0.00, "female":  0.00},
    "athletic": {"male": +0.04, "female": +0.03},
    "heavy":    {"male": +0.02, "female": +0.02},
}

# How strongly each measurement responds to the BMI scale.
# 0.0 = length (not scaled), 1.0 = full BMI effect.
MEASUREMENT_SENSITIVITY: dict[str, float] = {
    "waist_circum_cm":    1.00,
    "hip_circum_cm":      1.00,
    "thigh_circum_cm":    0.90,
    "chest_circum_cm":    0.85,
    "upperarm_circum_cm": 0.80,
    "calf_circum_cm":     0.60,
    "neck_circum_cm":     0.50,
    # lengths — not affected by BMI
    "shoulder_width_cm":  0.0,
    "sleeve_len_cm":      0.0,
    "pants_outseam_cm":   0.0,
    "top_len_cm":         0.0,
    "gown_len_cm":        0.0,
}

_SCALE_MIN = 0.88
_SCALE_MAX = 1.18


def _base_scale(bmi: float, gender: str) -> float:
    """Look up the base width scale from the BMI table."""
    col = 1 if gender == "male" else 2
    for row in BMI_SCALE_TABLE:
        if bmi <= row[0]:
            return row[col]
    return BMI_SCALE_TABLE[-1][col]


def get_width_scale(
    key: str,
    bmi: float,
    gender: str,
    body_type: Optional[str] = None,
) -> float:
    """Return the width scale for a specific measurement key.

    Parameters
    ----------
    key : str
        Measurement key, e.g. ``"chest_circum_cm"``.
    bmi : float
        User's BMI.
    gender : str
        ``"male"`` or ``"female"``.
    body_type : str or None
        Optional self-reported body type: ``"lean"``, ``"average"``,
        ``"athletic"``, or ``"heavy"``.

    Returns
    -------
    float
        Multiplicative width scale for this measurement (>= 0.88, <= 1.18).
        Length measurements always return 1.0.
    """
    sensitivity = MEASUREMENT_SENSITIVITY.get(key, 0.0)
    if sensitivity == 0.0:
        return 1.0

    base = _base_scale(bmi, gender)

    if body_type:
        adj = BODY_TYPE_ADJUSTMENT.get(body_type, {}).get(gender, 0.0)
        base = max(_SCALE_MIN, min(_SCALE_MAX, base + adj))

    # Apply sensitivity: interpolate between 1.0 (no effect) and base
    scaled = 1.0 + (base - 1.0) * sensitivity
    return round(max(_SCALE_MIN, min(_SCALE_MAX, scaled)), 4)


def get_uniform_width_scale(
    bmi: float,
    gender: str,
    body_type: Optional[str] = None,
) -> float:
    """Return the base width scale (no per-measurement sensitivity).

    This is useful as a single summary value for metadata/logging.
    """
    base = _base_scale(bmi, gender)
    if body_type:
        adj = BODY_TYPE_ADJUSTMENT.get(body_type, {}).get(gender, 0.0)
        base = max(_SCALE_MIN, min(_SCALE_MAX, base + adj))
    return round(base, 4)
