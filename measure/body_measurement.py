"""
Body measurement calculation from SMPL mesh data.
"""
import json
import math
from typing import Dict, Any, Tuple

import numpy as np
from scipy.spatial import ConvexHull


class BodyMeasurement:
    """Body measurement calculation from SMPL mesh vertices and joints."""

    @staticmethod
    def width_scale_from_weight_height(
        weight_kg: float,
        height_cm: float,
        *,
        base_width: float = 0.80,
        bmi_ref: float = 23.0,
        power: float = 0.25,
        min_scale: float = 0.70,
        max_scale: float = 1.15
    ) -> Tuple[float, float]:
        """Calculate width_scale from BMI (user height/weight)."""
        h_m = max(0.01, float(height_cm) / 100.0)
        bmi = float(weight_kg) / (h_m ** 2)
        ratio = (bmi / bmi_ref) ** power
        ws = base_width * ratio
        ws = max(min_scale, min(max_scale, ws))
        return float(ws), float(bmi)

    @staticmethod
    def _perimeter_convex(pts: np.ndarray) -> float:
        """Calculate perimeter of convex hull."""
        if pts.shape[0] < 3:
            return np.nan
        try:
            hull = ConvexHull(pts)
        except Exception:
            return np.nan
        verts = hull.vertices
        return float(sum(
            np.linalg.norm(pts[verts[i]] - pts[verts[(i + 1) % len(verts)]])
            for i in range(len(verts))
        ))

    @staticmethod
    def _slice_points_xy(vertices: np.ndarray, y0: float, tol: float = 0.008) -> np.ndarray:
        """Get points at a horizontal slice."""
        y = vertices[:, 1]
        m = np.abs(y - y0) < tol
        pts = vertices[m][:, [0, 2]]
        if pts.shape[0] < 3:
            return np.empty((0, 2))
        return pts - pts.mean(axis=0)

    @classmethod
    def _slice_points(cls, vertices: np.ndarray, y0: float, tol: float = 0.0075) -> np.ndarray:
        """Get points at a horizontal slice."""
        y = vertices[:, 1]
        m = np.abs(y - y0) < tol
        pts = vertices[m][:, [0, 2]]
        if pts.shape[0] < 3:
            return np.empty((0, 2))
        return pts - pts.mean(axis=0)

    @classmethod
    def _scan_perimeter_between(
        cls,
        vertices: np.ndarray,
        y_min: float,
        y_max: float,
        step: float = 0.005
    ) -> np.ndarray:
        """Scan perimeter between two Y values."""
        if y_max <= y_min:
            return np.empty((0, 2))
        ys = np.arange(y_min, y_max, step)
        if ys.size == 0:
            ys = np.linspace(y_min, y_max, 3)
        vals = []
        for y0 in ys:
            per = cls._perimeter_convex(cls._slice_points(vertices, y0))
            vals.append([y0, per])
        return np.asarray(vals, float)

    @classmethod
    def _orth_slice_along_segment_robust(
        cls,
        vertices: np.ndarray,
        p0: np.ndarray,
        p1: np.ndarray,
        t_list=(0.3, 0.4, 0.5, 0.6),
        radius=0.14,
        tol=0.012,
        horiz_fallback=True
    ) -> float:
        """Calculate orthogonal slice perimeter along a segment."""
        v = p1 - p0
        nv = np.linalg.norm(v)
        if nv < 1e-6:
            return np.nan
        v = v / nv

        a = np.array([1.0, 0.0, 0.0])
        if abs(a @ v) > 0.9:
            a = np.array([0.0, 1.0, 0.0])
        u = np.cross(v, a)
        u = u / np.linalg.norm(u)
        w = np.cross(v, u)

        best = np.nan
        for t in t_list:
            c = p0 + t * (p1 - p0)
            X = vertices - c
            proj = X @ v
            ortho = X - np.outer(proj, v)
            dist = np.linalg.norm(ortho, axis=1)

            tube = dist < radius
            if not np.any(tube):
                continue
            slab = np.abs(proj[tube]) < tol
            pts3 = (vertices[tube])[slab]
            if pts3.shape[0] < 3:
                continue

            rel = pts3 - c
            pts2 = np.stack([rel @ u, rel @ w], axis=1)
            per = cls._perimeter_convex(pts2)
            if np.isfinite(per):
                best = per if not np.isfinite(best) else max(best, per)

        if not np.isfinite(best) and horiz_fallback:
            y_mid = 0.5 * (p0[1] + p1[1])
            pts2 = cls._slice_points_xy(vertices, y_mid, tol=max(0.010, tol))
            per = cls._perimeter_convex(pts2)
            if np.isfinite(per):
                best = per
        return best

    @staticmethod
    def _body_height_y(vertices: np.ndarray) -> float:
        """Get body height from vertices."""
        return float(vertices[:, 1].max() - vertices[:, 1].min())

    @classmethod
    def _rescale_to_user_height(
        cls,
        vertices: np.ndarray,
        joints: np.ndarray,
        user_height_m: float,
        width_scale: float = 1.0
    ):
        """Rescale mesh to user height."""
        h = cls._body_height_y(vertices)
        s = user_height_m / max(h, 1e-6)
        V = vertices * s
        J = joints * s
        if abs(width_scale - 1.0) > 1e-6:
            V = V.copy()
            V[:, [0, 2]] *= float(width_scale)
        return V, J, s

    @staticmethod
    def _joint_map_custom() -> dict:
        """Joint index mapping."""
        return {
            "pelvis": 9,
            "left_hip": 8, "right_hip": 12,
            "left_knee": 3, "right_knee": 4,
            "left_ankle": 7, "right_ankle": 6,
            "neck": 22,
            "left_shoulder": 20, "right_shoulder": 21,
            "left_elbow": 18, "right_elbow": 19,
            "left_wrist": 16, "right_wrist": 17,
        }

    @staticmethod
    def _avg_y_mp(joints: np.ndarray, mp: dict, a: str, b: str) -> float:
        """Average Y coordinate of two joints."""
        return 0.5 * (joints[mp[a], 1] + joints[mp[b], 1])

    @staticmethod
    def _ground_y_from_ankles_or_mesh(
        joints: np.ndarray,
        vertices: np.ndarray,
        mp: dict
    ) -> float:
        """Get ground Y level from ankles or mesh."""
        ankles = float(min(joints[mp["left_ankle"], 1], joints[mp["right_ankle"], 1]))
        floor = float(vertices[:, 1].min())
        return min(ankles, floor)

    @classmethod
    def _measure_core(cls, vertices: np.ndarray, joints: np.ndarray) -> dict:
        """Core measurement calculation."""
        res = {}
        mp = cls._joint_map_custom()

        y_neck = float(joints[mp["neck"], 1])
        y_pelvis = float(joints[mp["pelvis"], 1])
        y_mid = 0.5 * (y_neck + y_pelvis)

        # Chest
        scan_chest = cls._scan_perimeter_between(vertices, y_mid, y_neck - 0.02, step=0.004)
        res["chest_circum_cm"] = float(np.nanmean(scan_chest[:, 1]) * 100) if scan_chest.size else np.nan

        # Waist
        scan_waist = cls._scan_perimeter_between(vertices, y_pelvis + 0.03, y_mid, step=0.004)
        res["waist_circum_cm"] = float(np.nanmean(scan_waist[:, 1]) * 100) if scan_waist.size else np.nan

        # Hip
        y_hips_mean = cls._avg_y_mp(joints, mp, "left_hip", "right_hip")
        scan_hip = cls._scan_perimeter_between(vertices, y_hips_mean - 0.18, y_hips_mean + 0.05, step=0.004)
        res["hip_circum_cm"] = float(np.nanmean(scan_hip[:, 1]) * 100) if scan_hip.size else np.nan

        # Upper Arm
        L_sh, L_el = joints[mp["left_shoulder"]], joints[mp["left_elbow"]]
        R_sh, R_el = joints[mp["right_shoulder"]], joints[mp["right_elbow"]]
        res["upperarm_circum_cm"] = float(np.nanmean([
            cls._orth_slice_along_segment_robust(vertices, L_sh, L_el),
            cls._orth_slice_along_segment_robust(vertices, R_sh, R_el)
        ]) * 100.0)

        # Thigh
        L_hp, L_kn = joints[mp["left_hip"]], joints[mp["left_knee"]]
        R_hp, R_kn = joints[mp["right_hip"]], joints[mp["right_knee"]]
        res["thigh_circum_cm"] = float(np.nanmean([
            cls._orth_slice_along_segment_robust(vertices, L_hp, L_kn),
            cls._orth_slice_along_segment_robust(vertices, R_hp, R_kn)
        ]) * 100.0)

        # Outseam
        y_hips_mean = cls._avg_y_mp(joints, mp, "left_hip", "right_hip")
        y_ground = cls._ground_y_from_ankles_or_mesh(joints, vertices, mp)
        res["pants_outseam_cm"] = float(max(0.0, y_hips_mean - y_ground) * 100.0)

        # Lengths
        res["sleeve_len_cm"] = 70.0
        res["top_len_cm"] = float(max(0.0, y_neck - (y_hips_mean + 0.02)) * 100)
        res["gown_len_cm"] = float(max(0.0, y_neck - y_ground) * 100)
        return res

    @classmethod
    def measure_pipeline(
        cls,
        vertices: np.ndarray,
        joints: np.ndarray,
        user_height_cm: float,
        gender: str = "male",
        width_scale: float = 0.75
    ) -> dict:
        """Main measurement pipeline."""
        V, J, s = cls._rescale_to_user_height(vertices, joints, user_height_cm / 100.0, width_scale)
        res = cls._measure_core(V, J)
        res.update({
            "gender": gender,
            "user_height_cm": float(user_height_cm),
            "scale_factor": float(s),
            "width_scale": float(width_scale),
        })
        return res

    @classmethod
    def measure_from_npz(
        cls,
        npz_path: str,
        user_height_cm: float,
        gender: str = "male",
        width_scale: float = 0.75
    ) -> dict:
        """Load NPZ and run measurement pipeline."""
        data = np.load(npz_path, allow_pickle=True)
        if "vertices" not in data or "joints" not in data:
            raise ValueError(f"Invalid npz: {npz_path}")
        vertices = np.asarray(data["vertices"])
        joints = np.asarray(data["joints"])
        return cls.measure_pipeline(vertices, joints, user_height_cm, gender, width_scale)

    @staticmethod
    def pretty_farsi(results: dict) -> dict:
        """Convert results to Farsi labels."""
        labels = {
            "chest_circum_cm": "دور سینه",
            "waist_circum_cm": "دور کمر",
            "hip_circum_cm": "دور باسن",
            "upperarm_circum_cm": "دور بازو",
            "thigh_circum_cm": "دور ران",
            "pants_outseam_cm": "قد بیرونی شلوار",
            "sleeve_len_cm": "قد آستین",
            "top_len_cm": "قد بالاتنه (بلوز)",
            "gown_len_cm": "قد لباس بلند",
            "user_height_cm": "قد کاربر",
            "scale_factor": "ضریب مقیاس مدل",
            "width_scale": "ضریب پهنای بدن",
            "gender": "جنسیت",
        }
        output = {}
        for k, label in labels.items():
            if k in results:
                v = results[k]
                if isinstance(v, (int, float)) and np.isfinite(v):
                    unit = "سانتی‌متر" if k.endswith("_cm") else ""
                    output[k] = f"{label}: {v:.1f} {unit}".strip()
                elif isinstance(v, str):
                    output[k] = f"{label}: {v}"
        return output
