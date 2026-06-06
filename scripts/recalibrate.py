"""
Weekly batch recalibration from purchase fit feedback.

Reads fit_feedback records from the Laravel internal API, groups them by
(gender, bmi_band, measurement_key), and updates calibration offsets when
a group has enough samples (default: 30).

Can be run standalone::

    python -m scripts.recalibrate

Or as a Celery task via ``app.tasks.cleanup.run_recalibration``.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from statistics import mean
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Minimum samples per (gender, bmi_band, key) group before updating offsets.
MIN_SAMPLES = 30

# How aggressively to move offsets toward the feedback signal.
LEARNING_RATE = 0.3

# Approximate cm difference that one size step represents, per measurement.
# Used to convert a discrete fit signal (-1/0/+1) into a cm delta.
AVG_SIZE_STEP_CM: dict[str, float] = {
    "chest_circum_cm":    3.0,
    "waist_circum_cm":    3.0,
    "hip_circum_cm":      3.0,
    "neck_circum_cm":     1.0,
    "upperarm_circum_cm": 1.5,
    "thigh_circum_cm":    2.0,
    "calf_circum_cm":     1.5,
    "shoulder_width_cm":  1.5,
    "sleeve_len_cm":      2.0,
    "pants_outseam_cm":   2.5,
}

# BMI band boundaries
_BMI_BANDS = [
    (18.5, "underweight"),
    (25.0, "normal"),
    (30.0, "overweight"),
    (float("inf"), "obese"),
]


def _bmi_band(bmi: float) -> str:
    for upper, label in _BMI_BANDS:
        if bmi < upper:
            return label
    return "obese"


def _compute_bmi(weight_kg: float, height_cm: float) -> float:
    height_m = height_cm / 100.0
    if height_m <= 0:
        return 22.0
    return weight_kg / (height_m * height_m)


def fetch_feedback(base_url: str, api_key: str) -> list[dict]:
    """Fetch fit feedback records from the Laravel internal API."""
    headers = {
        "X-Internal-Key": api_key,
        "Accept": "application/json",
    }
    try:
        resp = httpx.get(
            f"{base_url.rstrip('/')}/api/internal/fit-feedback",
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        records = data.get("data") if isinstance(data.get("data"), list) else data
        if isinstance(records, list):
            return records
        return []
    except Exception as e:
        logger.error("Failed to fetch fit feedback: %s", e)
        return []


def recalibrate(
    min_samples: int = MIN_SAMPLES,
    learning_rate: float = LEARNING_RATE,
    dry_run: bool = False,
) -> dict[str, dict[str, float]]:
    """Run recalibration from fit feedback data.

    Returns a dict of updated offsets keyed by ``gender.bmi_band``, e.g.::

        {
            "male.normal":  {"chest_circum_cm": 3.5, ...},
            "female.obese": {"waist_circum_cm": 4.8, ...},
        }
    """
    from measure.calibration import CALIBRATION_OFFSETS, load_offsets, save_offsets

    internal_url = getattr(settings, "internal_api_url", "") or ""
    internal_key = getattr(settings, "internal_api_key", "") or ""

    if not internal_url:
        logger.warning("INTERNAL_API_URL not set — cannot fetch feedback")
        return {}

    rows = fetch_feedback(internal_url, internal_key)
    if not rows:
        logger.info("No fit feedback records found — nothing to recalibrate")
        return {}

    logger.info("Processing %d fit feedback records", len(rows))

    # Group by (gender, bmi_band, measurement_key)
    groups: dict[tuple[str, str, str], list[float]] = {}

    for row in rows:
        fit_signal = row.get("fit_signal")
        if fit_signal is None:
            continue
        fit_signal = int(fit_signal)
        if fit_signal == 0:
            continue  # "perfect" — no correction needed

        snapshot = row.get("measurement_snapshot")
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(snapshot, dict):
            continue

        gender = snapshot.get("gender", "male")
        weight = snapshot.get("weight_kg") or snapshot.get("weight")
        height = snapshot.get("height_cm") or snapshot.get("height")

        if not weight or not height:
            bmi_b = "normal"
        else:
            bmi_b = _bmi_band(_compute_bmi(float(weight), float(height)))

        # fit_signal: -1 = tight (measured too small → increase offset)
        #             +1 = loose (measured too large → decrease offset)
        for key, step_cm in AVG_SIZE_STEP_CM.items():
            if key in snapshot:
                delta = fit_signal * step_cm
                groups.setdefault((gender, bmi_b, key), []).append(delta)

    # Compute new offsets for groups with enough samples
    updated: dict[str, dict[str, float]] = {}
    stats_log: list[str] = []

    for (gender, bmi_b, key), deltas in groups.items():
        if len(deltas) < min_samples:
            stats_log.append(
                f"  SKIP {gender}.{bmi_b}.{key}: {len(deltas)} samples < {min_samples}"
            )
            continue

        mean_delta = mean(deltas)
        current_offset = CALIBRATION_OFFSETS.get(gender, {}).get(key, 0.0)
        new_offset = round(current_offset + mean_delta * learning_rate, 2)

        group_key = f"{gender}.{bmi_b}"
        updated.setdefault(group_key, {})[key] = new_offset

        stats_log.append(
            f"  UPDATE {gender}.{bmi_b}.{key}: "
            f"n={len(deltas)}, mean_delta={mean_delta:+.2f}, "
            f"offset {current_offset:.2f} -> {new_offset:.2f}"
        )

    if stats_log:
        logger.info("Recalibration results:\n%s", "\n".join(stats_log))

    if not updated:
        logger.info("No groups met the minimum sample threshold — no offsets updated")
        return updated

    if dry_run:
        logger.info("DRY RUN — offsets NOT saved")
        return updated

    # Merge into the JSON offset file (layered on top of built-in offsets)
    existing = load_offsets()
    for group_key, offsets in updated.items():
        section = existing.setdefault(group_key, {})
        section.update(offsets)

    offsets_path = Path(__file__).resolve().parent.parent / "measure" / "data" / "calibration_offsets.json"
    save_offsets(existing, str(offsets_path))

    logger.info("Saved updated offsets to %s", offsets_path)
    return updated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = recalibrate(dry_run=False)
    if result:
        print(f"Updated {sum(len(v) for v in result.values())} offset(s) across {len(result)} group(s)")
    else:
        print("No offsets updated (insufficient data or no feedback)")
