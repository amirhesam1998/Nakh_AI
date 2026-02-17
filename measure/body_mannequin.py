"""
Body mannequin rendering from measurements.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional
import math

from PIL import Image, ImageDraw


def _safe(v: Optional[float], default: float) -> float:
    """Safe float conversion with default."""
    try:
        v = float(v)
        return v if math.isfinite(v) and v > 0 else default
    except (ValueError, TypeError):
        return default


def _circ_to_diam(circ_cm: Optional[float]) -> float:
    """Convert circumference to diameter (circle approximation)."""
    if not circ_cm or circ_cm <= 0:
        return 0.0
    return float(circ_cm / math.pi)


class BodyMannequinRenderer:
    """
    Render front mannequin with head/neck/torso/arms/legs from measurements.
    """

    def __init__(
        self,
        out_dir: Path,
        canvas_w_px: int = 900,
        bg="#222",
        fg="#2D66A3"
    ):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.canvas_w = canvas_w_px
        self.bg = bg
        self.fg = fg

    def _px_per_cm(self, height_cm: float) -> tuple:
        """Calculate pixels per cm scale and canvas height."""
        canvas_h = int(self.canvas_w * 1.6)
        scale = (canvas_h * 0.80) / max(1.0, height_cm)
        return scale, canvas_h

    def render(self, meas: Dict, file_name: str = "mannequin.png") -> str:
        """Render mannequin and save to file."""
        # Extract values with fallbacks
        H_cm = _safe(meas.get("user_height_cm"), 175.0)

        chest_c = _safe(meas.get("chest_circum_cm"), 100)
        waist_c = _safe(meas.get("waist_circum_cm"), 86)
        hip_c = _safe(meas.get("hip_circum_cm"), 102)

        thigh_c = _safe(meas.get("thigh_circum_cm"), 58)
        uarm_c = _safe(meas.get("upperarm_circum_cm"), 32)

        outseam_cm = _safe(meas.get("pants_outseam_cm"), H_cm * 0.45)
        sleeve_cm = _safe(meas.get("sleeve_len_cm"), H_cm * 0.26)
        top_len_cm = _safe(meas.get("top_len_cm"), H_cm * 0.30)

        # Pixel scale
        ppcm, canvas_h = self._px_per_cm(H_cm)
        W = self.canvas_w
        H = canvas_h
        cx = W // 2

        # Diameters from circumference
        chest_d = _circ_to_diam(chest_c)
        waist_d = _circ_to_diam(waist_c)
        hip_d = _circ_to_diam(hip_c)
        thigh_d = _circ_to_diam(thigh_c)
        uarm_d = _circ_to_diam(uarm_c)

        # To pixels
        chest_w = chest_d * ppcm
        waist_w = waist_d * ppcm
        hip_w = hip_d * ppcm
        thigh_w = thigh_d * ppcm
        uarm_w = uarm_d * ppcm

        # Lengths to pixels
        outseam_px = outseam_cm * ppcm
        sleeve_px = sleeve_cm * ppcm
        top_len_px = top_len_cm * ppcm

        # Vertical proportions
        head_h = 0.13 * H
        neck_h = 0.04 * H
        shoulder_y = int(H * 0.16)
        chest_y = int(H * 0.22)
        waist_y = int(H * 0.36)
        hip_y = int(H * 0.48)
        crotch_y = int(hip_y + 0.06 * H)

        # Shoulder width
        shoulder_w = max(chest_w * 1.05, uarm_w * 2.2, waist_w * 1.05)

        # Feet position
        feet_y = int(shoulder_y + head_h + neck_h + outseam_px)
        feet_y = min(H - 10, max(crotch_y + 40, feet_y))

        # Canvas
        img = Image.new("RGB", (W, H), self.bg)
        drw = ImageDraw.Draw(img)

        # Head (small ellipse)
        head_w = head_h * 0.78
        hx0 = cx - head_w / 2
        hx1 = cx + head_w / 2
        hy0 = shoulder_y - head_h - 6
        hy1 = shoulder_y - 6
        drw.ellipse([hx0, hy0, hx1, hy1], fill=self.fg)

        # Neck
        neck_w_top = head_w * 0.55
        neck_w_bot = min(shoulder_w * 0.50, chest_w * 0.55)
        nx0 = cx - neck_w_top / 2
        nx1 = cx + neck_w_top / 2
        nb0 = cx - neck_w_bot / 2
        nb1 = cx + neck_w_bot / 2
        drw.polygon([
            (nx0, hy1), (nx1, hy1),
            (nb1, shoulder_y), (nb0, shoulder_y)
        ], fill=self.fg)

        # Torso (chest -> waist -> hip)
        sw = shoulder_w / 2
        cw = chest_w / 2
        ww = waist_w / 2
        hw = hip_w / 2
        torso_pts = [
            (cx - sw, shoulder_y),
            (cx - cw, chest_y),
            (cx - ww, waist_y),
            (cx - hw, hip_y),
            (cx + hw, hip_y),
            (cx + ww, waist_y),
            (cx + cw, chest_y),
            (cx + sw, shoulder_y),
        ]
        drw.polygon(torso_pts, fill=self.fg)

        # Arms (left/right)
        arm_len = max(60, sleeve_px)
        arm_taper = max(0.6, min(0.95, (uarm_w * 0.7) / max(uarm_w, 1)))
        upper_y0 = shoulder_y + 6
        upper_y1 = upper_y0 + arm_len

        for side in (-1, +1):
            ax0 = cx + side * (sw + 6)
            ax1 = ax0 + side * (uarm_w * 0.55)
            ax2 = cx + side * (sw + 6 + (uarm_w * 0.55 * arm_taper))
            ax3 = ax2 + side * (uarm_w * 0.55)

            drw.polygon([
                (ax0, upper_y0),
                (ax1, upper_y0),
                (ax3, upper_y1),
                (ax2, upper_y1),
            ], fill=self.fg)

        # Legs
        calf_ratio = 0.55
        thigh_half = max(12, thigh_w * 0.5)
        calf_half = max(8, thigh_half * calf_ratio)

        gap = max(10, ww * 0.15)
        left_x_top = cx - gap / 2 - thigh_half
        right_x_top = cx + gap / 2 + thigh_half

        left_x_top_in = cx - gap / 2
        right_x_top_in = cx + gap / 2

        left_x_bot = cx - gap / 2 - calf_half
        right_x_bot = cx + gap / 2 + calf_half

        # Left leg
        drw.polygon([
            (left_x_top, crotch_y),
            (left_x_top_in, crotch_y),
            (left_x_bot, feet_y),
            (left_x_bot - 0.6 * calf_half, feet_y),
        ], fill=self.fg)

        # Right leg
        drw.polygon([
            (right_x_top_in, crotch_y),
            (right_x_top, crotch_y),
            (right_x_bot + 0.6 * calf_half, feet_y),
            (right_x_bot, feet_y),
        ], fill=self.fg)

        # Feet
        drw.rectangle([
            left_x_bot - 0.6 * calf_half, feet_y - 6,
            left_x_bot + 6, feet_y
        ], fill=self.fg)
        drw.rectangle([
            right_x_bot - 6, feet_y - 6,
            right_x_bot + 0.6 * calf_half, feet_y
        ], fill=self.fg)

        # Save
        out_path = self.out_dir / file_name
        img.save(out_path)
        return str(out_path)
