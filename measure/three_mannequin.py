"""
Three.js mannequin configuration builder.
"""
from __future__ import annotations

from typing import Dict, Any, Optional
import math


def _safe(v: Optional[float], default: float) -> float:
    """Safe float conversion with default."""
    try:
        v = float(v)
        return v if math.isfinite(v) and v > 0 else default
    except (ValueError, TypeError):
        return default


def _circ_to_radius_cm(circ: Optional[float]) -> float:
    """Convert circumference to radius."""
    if not circ or circ <= 0:
        return 10.0
    return float((circ / (2 * math.pi)))


def build_mannequin_config(meas: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build Three.js compatible mannequin configuration from measurements.

    Args:
        meas: Dictionary with measurement values (*_cm keys)

    Returns:
        Configuration dict for Three.js body rendering
    """
    H = _safe(meas.get("user_height_cm"), 175.0)

    chest = _safe(meas.get("chest_circum_cm"), 100)
    waist = _safe(meas.get("waist_circum_cm"), 86)
    hip = _safe(meas.get("hip_circum_cm"), 102)
    thigh = _safe(meas.get("thigh_circum_cm"), 58)
    uarm = _safe(meas.get("upperarm_circum_cm"), 32)
    sleeve = _safe(meas.get("sleeve_len_cm"), 0.26 * H)
    outseam = _safe(meas.get("pants_outseam_cm"), 0.45 * H)

    # Radii from circumference
    r_chest = _circ_to_radius_cm(chest)
    r_waist = _circ_to_radius_cm(waist)
    r_hip = _circ_to_radius_cm(hip)
    r_thigh = _circ_to_radius_cm(thigh) * 0.95
    r_uarm = _circ_to_radius_cm(uarm) * 0.95
    r_calf = r_thigh * 0.65
    r_fore = r_uarm * 0.7

    # Lengths
    head_h = 0.13 * H
    neck_h = 0.05 * H
    torso_h = 0.52 * H
    leg_h = outseam
    arm_h = sleeve

    # Shoulder span
    shoulder_span = max(2.1 * r_chest, 36.0)

    return {
        "units": "cm",
        "height_cm": H,
        "segments": {
            "head": {"h": head_h, "r": 0.45 * head_h},
            "neck": {
                "h": neck_h,
                "r_top": 0.45 * head_h * 0.55,
                "r_bot": r_chest * 0.55
            },
            "torso": {
                "h": torso_h,
                "r_top": r_chest,
                "r_mid": r_waist,
                "r_bot": r_hip,
                "shoulder_span": shoulder_span
            },
            "arm": {
                "h": arm_h,
                "r_up": r_uarm,
                "r_dn": r_fore
            },
            "leg": {
                "h": leg_h,
                "r_up": r_thigh,
                "r_dn": r_calf,
                "gap": max(4.0, r_waist * 0.35)
            }
        }
    }
