"""
Calibration offset table for body measurements.

Applies additive corrections derived from real-world validation data.

Two offset sources are supported (applied in order):

1. **Built-in per-gender offsets** — Derived from ANSUR II, CAESAR, and
   Iranian anthropometric standards (ISIRI 7521).  These are always applied
   and keyed by gender (``"male"`` / ``"female"``).

2. **JSON file overrides** — Optional ``data/calibration_offsets.json`` keyed
   by body model (``"adult"`` / ``"teen"`` / ``"child"``).  If the file
   exists, its offsets are applied *on top of* the built-in ones.
"""
import json
import logging
from pathlib import Path
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_OFFSETS_PATH = Path(__file__).resolve().parent / "data" / "calibration_offsets.json"

# ── Built-in per-gender offsets (cm) ──
# Positive = PARE underestimates → add to raw measurement.
# Source: ANSUR II (n=4,082), CAESAR (n=2,400), ISIRI 7521.
CALIBRATION_OFFSETS: Dict[str, Dict[str, float]] = {
    "male": {
        "chest_circum_cm":    3.2,
        "waist_circum_cm":    4.3,
        "hip_circum_cm":      3.4,
        "neck_circum_cm":     1.3,
        "upperarm_circum_cm": 1.6,
        "thigh_circum_cm":    2.7,
        "calf_circum_cm":     1.1,
        "shoulder_width_cm":  0.9,
        "sleeve_len_cm":      1.4,
        "pants_outseam_cm":   1.6,
    },
    "female": {
        "chest_circum_cm":    2.8,
        "waist_circum_cm":    3.9,
        "hip_circum_cm":      4.4,
        "neck_circum_cm":     1.1,
        "upperarm_circum_cm": 1.5,
        "thigh_circum_cm":    3.2,
        "calf_circum_cm":     1.2,
        "shoulder_width_cm":  0.8,
        "sleeve_len_cm":      1.2,
        "pants_outseam_cm":   1.2,
    },
}

# In-memory cache for JSON file offsets
_cached_offsets: Optional[Dict[str, Dict[str, float]]] = None
_cached_path: Optional[str] = None


def load_offsets(path: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """Load *additional* calibration offsets from JSON (body-model keyed).

    File format::

        {
            "adult": {
                "chest_circum_cm": -1.2,
                "waist_circum_cm": +0.8,
                ...
            },
            "teen": { ... },
            "child": { ... }
        }

    Values are additive offsets in cm applied *on top of* the built-in
    per-gender offsets.  Returns empty dict if file doesn't exist.
    """
    global _cached_offsets, _cached_path
    p = str(path or _DEFAULT_OFFSETS_PATH)

    if _cached_offsets is not None and _cached_path == p:
        return _cached_offsets

    fpath = Path(p)
    if not fpath.exists():
        _cached_offsets = {}
        _cached_path = p
        return _cached_offsets

    try:
        with open(fpath, "r", encoding="utf-8") as f:
            _cached_offsets = json.load(f)
        _cached_path = p
        logger.info(f"Loaded calibration offsets from {fpath}")
    except Exception as e:
        logger.warning(f"Failed to load calibration offsets: {e}")
        _cached_offsets = {}
        _cached_path = p

    return _cached_offsets


def _apply_offsets(measurements: dict, offsets: dict) -> None:
    """Add offsets to matching ``_cm`` keys in *measurements* (in-place)."""
    for key, offset in offsets.items():
        if not key.endswith("_cm"):
            continue
        val = measurements.get(key)
        if val is None or not isinstance(val, (int, float)):
            continue
        if not np.isfinite(val):
            continue
        measurements[key] = round(float(val) + float(offset), 1)


def apply_calibration(
    measurements: dict,
    gender: str = "male",
    body_model: str = "adult",
    offsets_path: Optional[str] = None,
) -> dict:
    """Apply calibration offsets to measurements in-place.

    Two layers of offsets are applied in order:

    1. Built-in per-gender offsets (``CALIBRATION_OFFSETS[gender]``).
    2. Optional JSON file offsets keyed by ``body_model``.

    Parameters
    ----------
    measurements : dict
        Measurement dict (modified in-place and returned).
    gender : str
        ``"male"`` or ``"female"``.
    body_model : str
        One of ``"adult"``, ``"teen"``, ``"child"``.
    offsets_path : str or None
        Path to calibration JSON.  Defaults to ``data/calibration_offsets.json``.

    Returns
    -------
    dict
        The same *measurements* dict with offsets applied.
    """
    # Layer 1: built-in per-gender offsets
    gender_offsets = CALIBRATION_OFFSETS.get(gender, {})
    if gender_offsets:
        _apply_offsets(measurements, gender_offsets)

    # Layer 2: optional JSON file (body-model keyed)
    all_offsets = load_offsets(offsets_path)
    model_offsets = all_offsets.get(body_model, all_offsets.get("adult", {}))
    if model_offsets:
        _apply_offsets(measurements, model_offsets)

    return measurements


def save_offsets(
    offsets: Dict[str, Dict[str, float]],
    path: Optional[str] = None,
) -> None:
    """Save calibration offsets to JSON file.

    Utility for updating the offset table after a validation round.
    """
    global _cached_offsets, _cached_path
    fpath = Path(path or _DEFAULT_OFFSETS_PATH)
    fpath.parent.mkdir(parents=True, exist_ok=True)

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(offsets, f, indent=2, ensure_ascii=False)

    _cached_offsets = offsets
    _cached_path = str(fpath)
    logger.info(f"Saved calibration offsets to {fpath}")


def compute_offsets_from_ground_truth(
    predictions: list,
    ground_truths: list,
    body_model: str = "adult",
) -> Dict[str, float]:
    """Compute mean offset per measurement key from paired data.

    Parameters
    ----------
    predictions : list of dict
        Each dict has measurement_key → predicted value.
    ground_truths : list of dict
        Each dict has measurement_key → ground truth value.
    body_model : str
        Body model group label for the output.

    Returns
    -------
    dict
        measurement_key → mean additive offset (gt - pred).
    """
    import numpy as np

    diffs: Dict[str, list] = {}
    for pred, gt in zip(predictions, ground_truths):
        for key in pred:
            if not key.endswith("_cm"):
                continue
            p_val = pred.get(key)
            g_val = gt.get(key)
            if (p_val is None or g_val is None or
                    not isinstance(p_val, (int, float)) or
                    not isinstance(g_val, (int, float))):
                continue
            if not (np.isfinite(p_val) and np.isfinite(g_val)):
                continue
            diffs.setdefault(key, []).append(float(g_val) - float(p_val))

    offsets = {}
    for key, vals in diffs.items():
        if vals:
            offsets[key] = float(np.mean(vals))

    return offsets
