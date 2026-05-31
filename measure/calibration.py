"""
Calibration offset table for body measurements.

Applies additive corrections derived from real-world validation data.
Offsets are stored in a JSON file and can be updated as more ground-truth
measurements are collected.
"""
import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_OFFSETS_PATH = Path(__file__).resolve().parent / "data" / "calibration_offsets.json"

# In-memory cache
_cached_offsets: Optional[Dict[str, Dict[str, float]]] = None
_cached_path: Optional[str] = None


def load_offsets(path: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """Load calibration offsets from JSON.

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

    Values are additive offsets in cm.  Positive = measured too small,
    negative = measured too large.

    Returns empty dict if file doesn't exist (no calibration applied).
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


def apply_calibration(
    measurements: dict,
    body_model: str = "adult",
    offsets_path: Optional[str] = None,
) -> dict:
    """Apply calibration offsets to measurements in-place.

    Only modifies keys that end with ``_cm`` and have a corresponding
    offset entry.  Non-numeric values are skipped.

    Parameters
    ----------
    measurements : dict
        Measurement dict (modified in-place and returned).
    body_model : str
        One of ``"adult"``, ``"teen"``, ``"child"``.
    offsets_path : str or None
        Path to calibration JSON.  Defaults to ``data/calibration_offsets.json``.

    Returns
    -------
    dict
        The same *measurements* dict with offsets applied.
    """
    all_offsets = load_offsets(offsets_path)
    offsets = all_offsets.get(body_model, all_offsets.get("adult", {}))

    if not offsets:
        return measurements

    for key, offset in offsets.items():
        if not key.endswith("_cm"):
            continue
        val = measurements.get(key)
        if val is None or not isinstance(val, (int, float)):
            continue
        import numpy as np
        if not np.isfinite(val):
            continue
        measurements[key] = float(val) + float(offset)

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
