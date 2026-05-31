"""
Size calculator: converts body measurements (cm) to standard clothing sizes.

Uses chest/bust, waist, and hip circumference to determine the best-fit size
label (XS–3XL or numeric) based on gender and body model.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Size charts: each entry is (label, chest_max, waist_max, hip_max) in cm.
# Values represent the upper bound for that size.

_MALE_ADULT = [
    ("XS", 88, 73, 88),
    ("S",  92, 78, 92),
    ("M",  96, 83, 96),
    ("L",  100, 88, 100),
    ("XL", 106, 95, 106),
    ("XXL", 112, 102, 112),
    ("3XL", 120, 110, 120),
]

_FEMALE_ADULT = [
    ("XS", 80, 60, 86),
    ("S",  84, 64, 90),
    ("M",  88, 68, 94),
    ("L",  92, 73, 98),
    ("XL", 98, 80, 104),
    ("XXL", 104, 87, 110),
    ("3XL", 112, 95, 118),
]

_CHILD = [
    ("2-3Y",  54, 51, 56),
    ("4-5Y",  58, 53, 60),
    ("6-7Y",  62, 55, 64),
    ("8-9Y",  66, 58, 68),
    ("10-11Y", 72, 62, 74),
    ("12-13Y", 78, 66, 80),
    ("14-15Y", 84, 70, 86),
]

_TEEN = [
    ("XS", 76, 62, 80),
    ("S",  80, 66, 84),
    ("M",  84, 70, 88),
    ("L",  88, 74, 92),
    ("XL", 94, 80, 98),
]


def _pick_chart(gender: str, body_model: str):
    if body_model == "child":
        return _CHILD
    if body_model == "teen":
        return _TEEN
    if gender == "female":
        return _FEMALE_ADULT
    return _MALE_ADULT


def calculate_size(
    measurements: dict,
    gender: str = "male",
    body_model: str = "adult",
) -> dict:
    """
    Calculate the user's clothing size from body measurements.

    Returns a dict with:
      - size: the best-fit label (e.g. "M", "L", "10-11Y")
      - size_numeric: numeric equivalent where applicable
      - details: per-measurement size breakdown
    """
    chart = _pick_chart(gender, body_model)

    chest = _get_cm(measurements, "chest_circumference", "bust_circumference")
    waist = _get_cm(measurements, "waist_circumference")
    hip = _get_cm(measurements, "hip_circumference")

    if not any([chest, waist, hip]):
        logger.warning("No circumference measurements found for size calculation")
        return {"size": None, "size_numeric": None, "details": {}}

    # For each measurement, find the matching size
    per_key = {}
    if chest:
        per_key["chest"] = _match(chart, 1, chest)
    if waist:
        per_key["waist"] = _match(chart, 2, waist)
    if hip:
        per_key["hip"] = _match(chart, 3, hip)

    # The overall size is the largest (most accommodating) across all measurements
    labels = [chart[i][0] for i in range(len(chart))]
    max_idx = 0
    for key, size_label in per_key.items():
        idx = next((i for i, row in enumerate(chart) if row[0] == size_label), 0)
        if idx > max_idx:
            max_idx = idx

    best_size = chart[max_idx][0]

    # Numeric size mapping (EU-style for pants)
    numeric = _to_numeric(best_size, gender, body_model, waist)

    return {
        "size": best_size,
        "size_numeric": numeric,
        "details": per_key,
    }


def _get_cm(measurements: dict, *keys) -> Optional[float]:
    for k in keys:
        v = measurements.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return None


def _match(chart: list, col: int, value: float) -> str:
    for row in chart:
        if value <= row[col]:
            return row[0]
    return chart[-1][0]  # largest size


def _to_numeric(
    size_label: str,
    gender: str,
    body_model: str,
    waist: Optional[float],
) -> Optional[int]:
    """Map letter size to numeric (EU pant size) where applicable."""
    if body_model in ("child", "teen"):
        return None

    # EU pant size approximation from waist
    if waist:
        eu = round(waist * 0.82 + 14)
        # Round to nearest even
        return eu if eu % 2 == 0 else eu + 1

    _map_m = {"XS": 42, "S": 44, "M": 46, "L": 48, "XL": 50, "XXL": 52, "3XL": 54}
    _map_f = {"XS": 34, "S": 36, "M": 38, "L": 40, "XL": 42, "XXL": 44, "3XL": 46}
    table = _map_f if gender == "female" else _map_m
    return table.get(size_label)


def recommend_from_available(
    measurements: dict,
    available_sizes: list[str],
    gender: str = "male",
    body_model: str = "adult",
) -> dict:
    """Pick the best size from a list of available sizes based on body measurements.

    Returns {recommended_size, calculated_size, confidence, details}.
    """
    if not available_sizes:
        return {"recommended_size": None, "calculated_size": None, "confidence": "low", "details": {}}

    calc = calculate_size(measurements, gender=gender, body_model=body_model)
    ideal = calc.get("size")
    ideal_numeric = calc.get("size_numeric")

    if not ideal:
        return {
            "recommended_size": available_sizes[0] if available_sizes else None,
            "calculated_size": None,
            "confidence": "low",
            "details": calc.get("details", {}),
        }

    # Normalise available sizes for comparison
    avail_upper = [s.upper().strip() for s in available_sizes]

    # Exact match
    if ideal.upper() in avail_upper:
        idx = avail_upper.index(ideal.upper())
        return {
            "recommended_size": available_sizes[idx],
            "calculated_size": ideal,
            "confidence": "high",
            "details": calc.get("details", {}),
        }

    # Check numeric match
    if ideal_numeric is not None:
        for i, s in enumerate(available_sizes):
            try:
                if int(float(s)) == ideal_numeric:
                    return {
                        "recommended_size": available_sizes[i],
                        "calculated_size": ideal,
                        "confidence": "high",
                        "details": calc.get("details", {}),
                    }
            except (ValueError, TypeError):
                continue

    # Find closest in letter-size order
    _letter_order = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL"]
    ideal_idx = next((i for i, l in enumerate(_letter_order) if l == ideal.upper()), None)

    if ideal_idx is not None:
        best_dist = 999
        best_match = None
        for i, s in enumerate(available_sizes):
            s_idx = next((j for j, l in enumerate(_letter_order) if l == s.upper().strip()), None)
            if s_idx is not None:
                dist = abs(s_idx - ideal_idx)
                if dist < best_dist:
                    best_dist = dist
                    best_match = available_sizes[i]
        if best_match:
            return {
                "recommended_size": best_match,
                "calculated_size": ideal,
                "confidence": "medium" if best_dist <= 1 else "low",
                "details": calc.get("details", {}),
            }

    # Numeric proximity fallback
    if ideal_numeric is not None:
        best_dist = 999
        best_match = None
        for i, s in enumerate(available_sizes):
            try:
                n = int(float(s))
                dist = abs(n - ideal_numeric)
                if dist < best_dist:
                    best_dist = dist
                    best_match = available_sizes[i]
            except (ValueError, TypeError):
                continue
        if best_match:
            return {
                "recommended_size": best_match,
                "calculated_size": ideal,
                "confidence": "medium" if best_dist <= 2 else "low",
                "details": calc.get("details", {}),
            }

    # Fallback: return the calculated size even if not in the list
    return {
        "recommended_size": available_sizes[len(available_sizes) // 2],
        "calculated_size": ideal,
        "confidence": "low",
        "details": calc.get("details", {}),
    }
