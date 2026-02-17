"""
MediaPipe-based body measurement from single images.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Union

import math
import numpy as np
import cv2
import mediapipe as mp

Number = Union[int, float]


@dataclass
class MPConfig:
    """MediaPipe measurement configuration."""
    height_cm: Optional[Number] = None
    weight_kg: Optional[Number] = None
    gender: Optional[str] = None
    min_vis: float = 0.5


class MediaPipeSingleMeasurer:
    """
    Measure body dimensions from single images using MediaPipe.
    """

    def __init__(self, cfg: MPConfig):
        self.cfg = cfg

    @staticmethod
    def _mid(p1, p2):
        """Calculate midpoint."""
        return ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)

    @staticmethod
    def _euclid(p1, p2) -> float:
        """Calculate Euclidean distance."""
        (x1, y1), (x2, y2) = p1, p2
        return float(math.hypot(x1 - x2, y1 - y2))

    @staticmethod
    def _safe_pt(
        lm,
        idx: int,
        w: int,
        h: int,
        clamp: bool = True
    ) -> Optional[Tuple[float, float, float, float, bool]]:
        """Safely extract point from landmarks."""
        if lm is None or not (0 <= idx < len(lm)):
            return None
        l = lm[idx]
        x, y = float(l.x), float(l.y)
        z = float(getattr(l, "z", 0.0))
        vis = float(getattr(l, "visibility", 0.0))
        in_frame = (0.0 <= x <= 1.0) and (0.0 <= y <= 1.0)
        if any(math.isnan(v) for v in (x, y, z, vis)):
            return None
        x_px, y_px = x * w, y * h
        if clamp:
            x_px = min(max(x_px, 0.0), float(w - 1))
            y_px = min(max(y_px, 0.0), float(h - 1))
        vis = min(max(vis, 0.0), 1.0)
        return (x_px, y_px, z, vis, in_frame)

    @staticmethod
    def _vis_ok(*args, thr: float = 0.5):
        """Check visibility of points."""
        def ok_one(a):
            if a is None:
                return False
            if isinstance(a, (tuple, list)):
                L = len(a)
                if L >= 5:
                    vis, in_frame = a[3], bool(a[4])
                    return in_frame and (vis is not None) and (vis >= thr)
                elif L >= 3:
                    vis = a[2]
                    return (vis is not None) and (vis >= thr)
                return False
            if isinstance(a, (int, float)):
                return a >= thr
            return False

        return all(ok_one(a) for a in args)

    def _estimate_pixel_height(self, lm, w, h, min_vis=0.5):
        """Estimate body height in pixels."""
        NOSE, L_HEEL, R_HEEL = 0, 29, 30
        n = self._safe_pt(lm, NOSE, w, h)
        lh = self._safe_pt(lm, L_HEEL, w, h)
        rh = self._safe_pt(lm, R_HEEL, w, h)
        if not self._vis_ok(n, lh, rh, thr=min_vis):
            return None
        heel_mid = self._mid((lh[0], lh[1]), (rh[0], rh[1]))
        nose_to_heel = abs(n[1] - heel_mid[1])
        return nose_to_heel * 1.08

    @staticmethod
    def _compute_bmi(
        height_cm: Optional[Number],
        weight_kg: Optional[Number]
    ) -> Optional[float]:
        """Compute BMI."""
        if not height_cm or not weight_kg:
            return None
        h_m = float(height_cm) / 100.0
        return float(weight_kg) / (h_m * h_m) if h_m > 0 else None

    @staticmethod
    def _depth_ratio_for_part(
        part: str,
        gender: Optional[str],
        bmi: Optional[float]
    ) -> float:
        """Get depth ratio for body part."""
        g = (gender or "").strip().lower()
        if part == "chest":
            base = 0.85 if g == "male" else 0.75
        elif part == "waist":
            base = 0.80 if g == "male" else 0.70
        elif part == "hip":
            base = 0.80 if g == "male" else 0.90
        elif part == "thigh":
            base = 0.95 if g == "male" else 0.90
        elif part == "upper_arm":
            base = 1.00
        else:
            base = 0.85
        if bmi is None:
            r = base
        else:
            delta = max(-0.1, min(0.1, 0.01 * (bmi - 25.0)))
            r = base + delta
        return float(max(0.55, min(1.10, r)))

    @staticmethod
    def _ellipse_c_from_axes(a: float, b: float) -> Optional[float]:
        """Calculate ellipse circumference from axes."""
        if a is None or b is None or a <= 0 or b <= 0:
            return None
        return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))

    @staticmethod
    def _ellipse_c_from_width(
        width: Optional[float],
        depth_ratio: Optional[float]
    ) -> Optional[float]:
        """Calculate ellipse circumference from width and depth ratio."""
        if width is None or depth_ratio is None:
            return None
        a = width * 0.5
        b = depth_ratio * width * 0.5
        return MediaPipeSingleMeasurer._ellipse_c_from_axes(a, b)

    @staticmethod
    def _px_to_cm(
        px: Optional[float],
        cm_per_px: Optional[float]
    ) -> Optional[float]:
        """Convert pixels to cm."""
        return float(px * cm_per_px) if (px is not None and cm_per_px) else None

    @staticmethod
    def _clamp(
        v: Optional[float],
        lo: Optional[float] = None,
        hi: Optional[float] = None
    ) -> Optional[float]:
        """Clamp value to range."""
        if v is None:
            return None
        if lo is not None:
            v = max(v, lo)
        if hi is not None:
            v = min(v, hi)
        return v

    def _upper_arm_diam_px(self, p_sho, p_elb, alpha=0.20) -> Optional[float]:
        """Estimate upper arm diameter in pixels."""
        if not self._vis_ok(p_sho, p_elb, thr=0.3):
            return None
        seg = self._euclid((p_sho[0], p_sho[1]), (p_elb[0], p_elb[1]))
        return seg * alpha

    def _thigh_diam_px(self, p_hip, p_knee, beta=0.20) -> Optional[float]:
        """Estimate thigh diameter in pixels."""
        if not self._vis_ok(p_hip, p_knee, thr=0.3):
            return None
        seg = self._euclid((p_hip[0], p_hip[1]), (p_knee[0], p_knee[1]))
        return seg * beta

    def measure_rgb(self, rgb: np.ndarray) -> Tuple[Dict[str, Any], Any]:
        """
        Measure body from RGB image.

        Args:
            rgb: RGB image array

        Returns:
            Tuple of (metrics_dict, mp_result)
        """
        mp_pose = mp.solutions.pose
        with mp_pose.Pose(static_image_mode=True, model_complexity=1) as pose:
            res = pose.process(rgb)
            if not res.pose_landmarks:
                raise RuntimeError("Pose landmarks not found.")

            lm = res.pose_landmarks.landmark
            h, w = rgb.shape[:2]

            # Landmark indices
            L_SHO, R_SHO = 11, 12
            L_ELB, R_ELB = 13, 14
            L_WRIST, R_WRIST = 15, 16
            L_HIP, R_HIP = 23, 24
            L_KNEE, R_KNEE = 25, 26
            L_ANKLE, R_ANKLE = 27, 28
            L_HEEL, R_HEEL = 29, 30

            pLsho = self._safe_pt(lm, L_SHO, w, h)
            pRsho = self._safe_pt(lm, R_SHO, w, h)
            pLelb = self._safe_pt(lm, L_ELB, w, h)
            pRelb = self._safe_pt(lm, R_ELB, w, h)
            pLwri = self._safe_pt(lm, L_WRIST, w, h)
            pRwri = self._safe_pt(lm, R_WRIST, w, h)
            pLhip = self._safe_pt(lm, L_HIP, w, h)
            pRhip = self._safe_pt(lm, R_HIP, w, h)
            pLkne = self._safe_pt(lm, L_KNEE, w, h)
            pRkne = self._safe_pt(lm, R_KNEE, w, h)
            pLank = self._safe_pt(lm, L_ANKLE, w, h)
            pRank = self._safe_pt(lm, R_ANKLE, w, h)
            pLhel = self._safe_pt(lm, L_HEEL, w, h)
            pRhel = self._safe_pt(lm, R_HEEL, w, h)

            # Scale
            cm_per_px = None
            px_height = self._estimate_pixel_height(lm, w, h)
            if self.cfg.height_cm and px_height and px_height > 0:
                cm_per_px = float(self.cfg.height_cm) / float(px_height)

            # Depth ratios
            bmi = self._compute_bmi(self.cfg.height_cm, self.cfg.weight_kg)
            raw_dr = {
                "chest": self._depth_ratio_for_part("chest", self.cfg.gender, bmi),
                "waist": self._depth_ratio_for_part("waist", self.cfg.gender, bmi),
                "hip": self._depth_ratio_for_part("hip", self.cfg.gender, bmi),
                "thigh": self._depth_ratio_for_part("thigh", self.cfg.gender, bmi),
                "upper_arm": self._depth_ratio_for_part("upper_arm", self.cfg.gender, bmi),
            }
            dr = {k: self._clamp(v, 0.60, 1.10) for k, v in raw_dr.items()}

            # Widths
            shoulder_px = (
                self._euclid((pLsho[0], pLsho[1]), (pRsho[0], pRsho[1]))
                if self._vis_ok(pLsho, pRsho, thr=self.cfg.min_vis) else None
            )
            chest_px = shoulder_px * 1.15 if shoulder_px else None

            pelvis_core_px = (
                self._euclid((pLhip[0], pLhip[1]), (pRhip[0], pRhip[1]))
                if self._vis_ok(pLhip, pRhip, thr=self.cfg.min_vis) else None
            )
            if pelvis_core_px:
                waist_px = pelvis_core_px * 1.60
                hip_px = pelvis_core_px * 1.75
            else:
                waist_px = hip_px = None

            tL = self._thigh_diam_px(pLhip, pLkne, beta=0.20)
            tR = self._thigh_diam_px(pRhip, pRkne, beta=0.20)
            thigh_width_px = max(tL, tR) if (tL and tR) else (tL or tR or None)

            uL = self._upper_arm_diam_px(pLsho, pLelb, alpha=0.20)
            uR = self._upper_arm_diam_px(pRsho, pRelb, alpha=0.20)
            upper_arm_width_px = max(uL, uR) if (uL and uR) else (uL or uR or None)

            # Lengths
            sleeve_L_px = (
                self._euclid((pLsho[0], pLsho[1]), (pLwri[0], pLwri[1]))
                if self._vis_ok(pLsho, pLwri, thr=self.cfg.min_vis) else None
            )
            sleeve_R_px = (
                self._euclid((pRsho[0], pRsho[1]), (pRwri[0], pRwri[1]))
                if self._vis_ok(pRsho, pRwri, thr=self.cfg.min_vis) else None
            )
            sleeve_px = (
                sleeve_L_px if sleeve_L_px and not sleeve_R_px else
                sleeve_R_px if sleeve_R_px and not sleeve_L_px else
                (0.5 * (sleeve_L_px + sleeve_R_px) if sleeve_L_px and sleeve_R_px else None)
            )

            if self._vis_ok(pLhip, pRhip, pLhel, pRhel, thr=0.3):
                waist_mid = self._mid((pLhip[0], pLhip[1]), (pRhip[0], pRhip[1]))
                heel_mid = self._mid((pLhel[0], pLhel[1]), (pRhel[0], pRhel[1]))
                outseam_px = self._euclid(waist_mid, heel_mid)
            else:
                outseam_px = None

            if self._vis_ok(pLhip, pRhip, pLank, pRank, thr=0.3):
                crotch = self._mid((pLhip[0], pLhip[1]), (pRhip[0], pRhip[1]))
                ankle_mid = self._mid((pLank[0], pLank[1]), (pRank[0], pRank[1]))
                inseam_px = self._euclid(crotch, ankle_mid)
            else:
                inseam_px = None

            if self._vis_ok(pLsho, pRsho, thr=0.3):
                neck_hollow = self._mid((pLsho[0], pLsho[1]), (pRsho[0], pRsho[1]))
                neck_hollow = (neck_hollow[0], neck_hollow[1] + 0.06 * abs(pLsho[1] - pRsho[1] + w * 0.0))
            else:
                neck_hollow = None

            hip_mid = (
                self._mid((pLhip[0], pLhip[1]), (pRhip[0], pRhip[1]))
                if self._vis_ok(pLhip, pRhip, thr=0.3) else None
            )
            floor_mid = (
                self._mid((pLhel[0], pLhel[1]), (pRhel[0], pRhel[1]))
                if self._vis_ok(pLhel, pRhel, thr=0.3) else None
            )

            top_len_px = self._euclid(neck_hollow, hip_mid) if (neck_hollow and hip_mid) else None
            dress_len_px = self._euclid(neck_hollow, floor_mid) if (neck_hollow and floor_mid) else None

            # Circumferences (ellipse)
            chest_circ_px = self._ellipse_c_from_width(chest_px, dr["chest"])
            waist_circ_px = self._ellipse_c_from_width(waist_px, dr["waist"])
            hip_circ_px = self._ellipse_c_from_width(hip_px, dr["hip"])
            thigh_circ_px = self._ellipse_c_from_width(thigh_width_px, dr["thigh"])
            uarm_circ_px = self._ellipse_c_from_width(upper_arm_width_px, dr["upper_arm"])

            if uarm_circ_px is not None and chest_circ_px is not None:
                uarm_circ_px = self._clamp(uarm_circ_px, lo=0.22 * chest_circ_px, hi=0.45 * chest_circ_px)
            if thigh_circ_px is not None and hip_circ_px is not None:
                thigh_circ_px = self._clamp(thigh_circ_px, lo=0.50 * hip_circ_px, hi=0.90 * hip_circ_px)

            def conv(x):
                return self._px_to_cm(x, cm_per_px)

            return {
                "engine": "mediapipe",
                "scale": {
                    "pixel_height_est": px_height,
                    "cm_per_px": cm_per_px,
                    "bmi": bmi,
                    "depth_ratios": dr,
                },
                "circumferences_cm": {
                    "chest": conv(chest_circ_px),
                    "waist": conv(waist_circ_px),
                    "hip": conv(hip_circ_px),
                    "thigh": conv(thigh_circ_px),
                    "upper_arm": conv(uarm_circ_px),
                },
                "lengths_cm": {
                    "pants_outseam": conv(outseam_px),
                    "sleeve": conv(sleeve_px),
                    "top_from_neck_hollow_to_hip": conv(top_len_px),
                    "dress_from_neck_hollow_to_floor": conv(dress_len_px),
                    "inseam_opt": conv(inseam_px),
                },
                "debug": {
                    "shoulder_width_px": shoulder_px,
                    "chest_width_px": chest_px,
                    "pelvis_core_px": pelvis_core_px,
                    "waist_width_px": waist_px,
                    "hip_width_px": hip_px,
                    "thigh_width_px": thigh_width_px,
                    "upper_arm_width_px": upper_arm_width_px,
                },
            }, res

    @staticmethod
    def _load_rgb(path: Union[str, Path]) -> np.ndarray:
        """Load image as RGB."""
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise RuntimeError(f"Cannot read: {path}")
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    def measure_paths(
        self,
        image_front: Union[str, Path],
        image_armsup: Optional[Union[str, Path]] = None,
        image_side: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """
        Measure from image paths.

        Args:
            image_front: Front view image path
            image_armsup: Arms-up view image path (optional)
            image_side: Side view image path (optional)

        Returns:
            Dictionary with measurements for each view
        """
        out: Dict[str, Any] = {}

        # Front
        rgb_front = self._load_rgb(image_front)
        out_front, res_front = self.measure_rgb(rgb_front)
        out["front"] = out_front

        # Arms-up
        if image_armsup:
            rgb_armsup = self._load_rgb(image_armsup)
            out_arm, _ = self.measure_rgb(rgb_armsup)
            out["armsup"] = out_arm

        # Side
        if image_side:
            rgb_side = self._load_rgb(image_side)
            side_out, _ = self.measure_rgb(rgb_side)
            out["side"] = side_out

        return out
