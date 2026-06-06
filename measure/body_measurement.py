"""
Body measurement calculation from SMPL mesh data.
"""
import json
import math
import pickle
from pathlib import Path
from typing import Dict, Any, Tuple

import numpy as np
from scipy.spatial import ConvexHull

from measure.alpha_shape import alpha_shape_perimeter
from measure.bmi_scaling import get_width_scale, get_uniform_width_scale


class BodyMeasurement:
    """Body measurement calculation from SMPL mesh vertices and joints."""

    @staticmethod
    def width_scale_from_weight_height(
        weight_kg: float,
        height_cm: float,
        *,
        bmi_ref: float = 23.0,
        power: float = 0.15,
        min_scale: float = 0.90,
        max_scale: float = 1.12
    ) -> Tuple[float, float]:
        """Soft BMI prior for circumference correction.

        Uses (bmi/23)^0.15 clamped to [0.90, 1.12].  This is a gentle
        nudge — not a heavy scaling — so that SMPL-derived circumferences
        are only lightly adjusted toward the user's actual body composition.
        """
        h_m = max(0.01, float(height_cm) / 100.0)
        bmi = float(weight_kg) / (h_m ** 2)
        ws = (bmi / bmi_ref) ** power
        ws = max(min_scale, min(max_scale, ws))
        return float(ws), float(bmi)

    @staticmethod
    def _perimeter_convex(pts: np.ndarray) -> float:
        """Calculate perimeter of convex hull (fallback for limb slices)."""
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
    def _perimeter_alpha(pts: np.ndarray) -> float:
        """Calculate perimeter using alpha-shape (concave hull).

        Better than convex hull for torso cross-sections where the
        body has natural concavities (waist, armpit area).
        Falls back to convex hull on failure.
        """
        if pts.shape[0] < 3:
            return np.nan
        return alpha_shape_perimeter(pts, alpha=0.0)

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
        step: float = 0.005,
        use_alpha: bool = True,
    ) -> np.ndarray:
        """Scan perimeter between two Y values with IQR outlier rejection.

        When *use_alpha* is True, uses alpha-shape (concave hull) for
        tighter perimeters on torso cross-sections.
        """
        if y_max <= y_min:
            return np.empty((0, 2))
        ys = np.arange(y_min, y_max, step)
        if ys.size == 0:
            ys = np.linspace(y_min, y_max, 3)
        perim_fn = cls._perimeter_alpha if use_alpha else cls._perimeter_convex
        vals = []
        for y0 in ys:
            per = perim_fn(cls._slice_points(vertices, y0))
            vals.append([y0, per])
        arr = np.asarray(vals, float)
        if arr.size == 0:
            return arr
        # IQR-based outlier rejection on perimeter column
        perimeters = arr[:, 1]
        finite = np.isfinite(perimeters)
        if finite.sum() < 3:
            return arr
        q1, q3 = np.percentile(perimeters[finite], [25, 75])
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        keep = finite & (perimeters >= lo) & (perimeters <= hi)
        return arr[keep] if keep.any() else arr[finite]

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
    ):
        """Uniformly rescale mesh + joints so total height matches the user's.

        Returns (V, J, s) all in metres. Width adjustment (BMI fit) is NOT
        applied here — it is applied to *circumference* outputs only, by the
        caller, to avoid distorting the perpendicular cross-section frames
        used for limb circumferences.
        """
        h = cls._body_height_y(vertices)
        s = user_height_m / max(h, 1e-6)
        V = vertices * s
        J = joints * s
        return V, J, s

    @staticmethod
    def _joint_map_custom() -> dict:
        """Joint index mapping (PARE/SPIN 49-joint convention).

        Indices 0-24: OpenPose ordering
        Indices 25-48: Ground truth / extra joints
        See pare/core/constants.py JOINT_NAMES for the full list.
        """
        return {
            "pelvis": 8,       # OP MidHip
            "left_hip": 12, "right_hip": 9,
            "left_knee": 13, "right_knee": 10,
            "left_ankle": 14, "right_ankle": 11,
            "neck": 1,         # OP Neck
            "left_shoulder": 5, "right_shoulder": 2,
            "left_elbow": 6, "right_elbow": 3,
            "left_wrist": 7, "right_wrist": 4,
        }

    @staticmethod
    def _joint_map_smpl() -> dict:
        """Joint index mapping for SMPL's native 24/45-joint convention.

        Used when measuring from a consensus mesh built via smplx.SMPL.
        """
        return {
            "pelvis": 0,
            "left_hip": 1,    "right_hip": 2,
            "left_knee": 4,   "right_knee": 5,
            "left_ankle": 7,  "right_ankle": 8,
            "neck": 12,
            "left_shoulder": 16, "right_shoulder": 17,
            "left_elbow": 18,    "right_elbow": 19,
            "left_wrist": 20,    "right_wrist": 21,
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

    # SMPL body-part vertex segmentation
    _seg_data = None

    # Part groups for measurement filtering
    _TORSO_PARTS = {0, 3, 6, 9}          # Global, Spine, Spine1, Spine2
    _UPPER_ARM_PARTS = {13, 14, 16, 17}  # L/R Shoulder, L/R UpperArm
    _THIGH_PARTS = {1, 2}                # L/R Thigh
    _CALF_PARTS = {4, 5}                 # L/R Calf
    _NECK_PARTS = {12}                   # Neck

    @classmethod
    def _load_segmentation(cls) -> np.ndarray:
        """Load SMPL vertex-to-part mapping (cached)."""
        if cls._seg_data is None:
            seg_path = (
                Path(__file__).resolve().parent
                / "PARE" / "scripts" / "data" / "smpl_partSegmentation_mapping.pkl"
            )
            if seg_path.exists():
                with open(seg_path, "rb") as f:
                    raw = pickle.load(f, encoding="latin1")
                cls._seg_data = np.asarray(raw["smpl_index"])
            else:
                cls._seg_data = np.array([], dtype=int)
        return cls._seg_data

    @classmethod
    def _filter_vertices_by_parts(
        cls, vertices: np.ndarray, part_ids: set
    ) -> np.ndarray:
        """Return only vertices belonging to the given SMPL part IDs."""
        seg = cls._load_segmentation()
        if seg.size == 0 or seg.size != vertices.shape[0]:
            return vertices
        mask = np.isin(seg, list(part_ids))
        filtered = vertices[mask]
        return filtered if filtered.shape[0] >= 10 else vertices

    @classmethod
    def _measure_core(cls, vertices: np.ndarray, joints: np.ndarray) -> dict:
        """Core measurement using PARE/OpenPose 49-joint convention."""
        return cls._measure_core_impl(vertices, joints, cls._joint_map_custom())

    # Keys that represent a *circumference* and should be multiplied by
    # width_scale to reflect BMI-driven body width.
    _CIRCUM_KEYS = (
        "chest_circum_cm",
        "waist_circum_cm",
        "hip_circum_cm",
        "upperarm_circum_cm",
        "thigh_circum_cm",
        "calf_circum_cm",
        "neck_circum_cm",
    )

    @classmethod
    def measure_pipeline(
        cls,
        vertices: np.ndarray,
        joints: np.ndarray,
        user_height_cm: float,
        gender: str = "male",
        width_scale: float = 0.75,
        bmi: float | None = None,
        body_type: str | None = None,
    ) -> dict:
        """Main measurement pipeline.

        Mesh is uniformly scaled to the user's height.  Per-measurement
        BMI width scaling is applied to circumferences only (not to
        lengths), so the cross-section frames stay isotropic.

        If *bmi* is provided, per-measurement lookup-table scaling is
        used (see ``bmi_scaling.py``).  Otherwise the legacy uniform
        *width_scale* is applied.
        """
        V, J, s = cls._rescale_to_user_height(vertices, joints, user_height_cm / 100.0)
        res = cls._measure_core(V, J)

        if bmi is not None:
            ws_summary = get_uniform_width_scale(bmi, gender, body_type)
            for k in cls._CIRCUM_KEYS:
                v = res.get(k)
                if v is not None and isinstance(v, (int, float)) and np.isfinite(v):
                    res[k] = float(v) * get_width_scale(k, bmi, gender, body_type)
        else:
            ws_summary = float(width_scale)
            for k in cls._CIRCUM_KEYS:
                v = res.get(k)
                if v is not None and isinstance(v, (int, float)) and np.isfinite(v):
                    res[k] = float(v) * ws_summary

        res.update({
            "gender": gender,
            "user_height_cm": float(user_height_cm),
            "scale_factor": float(s),
            "width_scale": ws_summary,
        })
        return res

    @classmethod
    def measure_from_npz(
        cls,
        npz_path: str,
        user_height_cm: float,
        gender: str = "male",
        width_scale: float = 0.75,
        bmi: float | None = None,
        body_type: str | None = None,
    ) -> dict:
        """Load NPZ and run measurement pipeline."""
        data = np.load(npz_path, allow_pickle=True)
        if "vertices" not in data or "joints" not in data:
            raise ValueError(f"Invalid npz: {npz_path}")
        vertices = np.asarray(data["vertices"])
        joints = np.asarray(data["joints"])
        return cls.measure_pipeline(
            vertices, joints, user_height_cm, gender, width_scale,
            bmi=bmi, body_type=body_type,
        )

    @classmethod
    def measure_consensus(
        cls,
        vertices: np.ndarray,
        joints: np.ndarray,
        user_height_cm: float,
        gender: str = "male",
        width_scale: float = 1.0,
        bmi: float | None = None,
        body_type: str | None = None,
    ) -> dict:
        """Measure from a consensus SMPL mesh (45-joint format).

        This is the primary measurement path for the consensus-mesh pipeline.
        It uses SMPL's native joint ordering instead of PARE/OpenPose ordering.

        If *bmi* is provided, per-measurement lookup-table scaling is
        used (see ``bmi_scaling.py``).  Otherwise the legacy uniform
        *width_scale* is applied.
        """
        # Scale to real height
        V, J, s = cls._rescale_to_user_height(vertices, joints, user_height_cm / 100.0)

        # Use SMPL joint map
        mp = cls._joint_map_smpl()
        res = cls._measure_core_impl(V, J, mp)

        # Apply per-measurement BMI width scaling to circumferences only
        if bmi is not None:
            ws_summary = get_uniform_width_scale(bmi, gender, body_type)
            for k in cls._CIRCUM_KEYS:
                v = res.get(k)
                if v is not None and isinstance(v, (int, float)) and np.isfinite(v):
                    res[k] = float(v) * get_width_scale(k, bmi, gender, body_type)
        else:
            ws_summary = float(width_scale)
            for k in cls._CIRCUM_KEYS:
                v = res.get(k)
                if v is not None and isinstance(v, (int, float)) and np.isfinite(v):
                    res[k] = float(v) * ws_summary

        res.update({
            "gender": gender,
            "user_height_cm": float(user_height_cm),
            "scale_factor": float(s),
            "width_scale": ws_summary,
        })
        return res

    @classmethod
    def _measure_core_impl(cls, vertices: np.ndarray, joints: np.ndarray, mp: dict) -> dict:
        """Core measurement logic, parameterised by joint map.

        Works with any joint convention as long as ``mp`` provides the
        expected joint name → index mapping.
        """
        res = {}

        y_neck = float(joints[mp["neck"], 1])
        y_pelvis = float(joints[mp["pelvis"], 1])
        y_mid = 0.5 * (y_neck + y_pelvis)

        # Filter torso vertices (exclude arms, legs, head)
        torso_verts = cls._filter_vertices_by_parts(vertices, cls._TORSO_PARTS)

        # Chest
        scan_chest = cls._scan_perimeter_between(torso_verts, y_mid, y_neck - 0.02, step=0.004)
        res["chest_circum_cm"] = float(np.nanmedian(scan_chest[:, 1]) * 100) if scan_chest.size else np.nan

        # Waist
        scan_waist = cls._scan_perimeter_between(torso_verts, y_pelvis + 0.03, y_mid, step=0.004)
        res["waist_circum_cm"] = float(np.nanmedian(scan_waist[:, 1]) * 100) if scan_waist.size else np.nan

        # Hip
        y_hips_mean = cls._avg_y_mp(joints, mp, "left_hip", "right_hip")
        hip_parts = cls._TORSO_PARTS | cls._THIGH_PARTS
        hip_verts = cls._filter_vertices_by_parts(vertices, hip_parts)
        scan_hip = cls._scan_perimeter_between(hip_verts, y_hips_mean - 0.18, y_hips_mean + 0.05, step=0.004)
        res["hip_circum_cm"] = float(np.nanmedian(scan_hip[:, 1]) * 100) if scan_hip.size else np.nan

        # Upper Arm
        arm_verts = cls._filter_vertices_by_parts(vertices, cls._UPPER_ARM_PARTS)
        L_sh, L_el = joints[mp["left_shoulder"]], joints[mp["left_elbow"]]
        R_sh, R_el = joints[mp["right_shoulder"]], joints[mp["right_elbow"]]
        res["upperarm_circum_cm"] = float(np.nanmean([
            cls._orth_slice_along_segment_robust(arm_verts, L_sh, L_el),
            cls._orth_slice_along_segment_robust(arm_verts, R_sh, R_el)
        ]) * 100.0)

        # Thigh
        thigh_verts = cls._filter_vertices_by_parts(vertices, cls._THIGH_PARTS)
        L_hp, L_kn = joints[mp["left_hip"]], joints[mp["left_knee"]]
        R_hp, R_kn = joints[mp["right_hip"]], joints[mp["right_knee"]]
        res["thigh_circum_cm"] = float(np.nanmean([
            cls._orth_slice_along_segment_robust(thigh_verts, L_hp, L_kn),
            cls._orth_slice_along_segment_robust(thigh_verts, R_hp, R_kn)
        ]) * 100.0)

        # Calf
        calf_verts = cls._filter_vertices_by_parts(vertices, cls._CALF_PARTS)
        L_an, R_an = joints[mp["left_ankle"]], joints[mp["right_ankle"]]
        res["calf_circum_cm"] = float(np.nanmean([
            cls._orth_slice_along_segment_robust(calf_verts, L_kn, L_an),
            cls._orth_slice_along_segment_robust(calf_verts, R_kn, R_an)
        ]) * 100.0)

        # Neck: scan within the actual neck-vertex Y range
        neck_verts = cls._filter_vertices_by_parts(vertices, cls._NECK_PARTS)
        if neck_verts.shape[0] >= 10:
            ny_min = float(neck_verts[:, 1].min()) + 0.005
            ny_max = float(neck_verts[:, 1].max()) - 0.005
            scan_neck = cls._scan_perimeter_between(neck_verts, ny_min, ny_max, step=0.004)
        else:
            y_neck = float(joints[mp["neck"], 1])
            scan_neck = cls._scan_perimeter_between(vertices, y_neck - 0.08, y_neck - 0.02, step=0.004)
        res["neck_circum_cm"] = float(np.nanmedian(scan_neck[:, 1]) * 100) if scan_neck.size else np.nan

        # Outseam
        y_hips_mean = cls._avg_y_mp(joints, mp, "left_hip", "right_hip")
        y_ground = cls._ground_y_from_ankles_or_mesh(joints, vertices, mp)
        res["pants_outseam_cm"] = float(max(0.0, y_hips_mean - y_ground) * 100.0)

        # Sleeve length
        L_sh, L_el, L_wr = (joints[mp[k]] for k in ("left_shoulder", "left_elbow", "left_wrist"))
        R_sh, R_el, R_wr = (joints[mp[k]] for k in ("right_shoulder", "right_elbow", "right_wrist"))
        sleeve_left = float(np.linalg.norm(L_el - L_sh) + np.linalg.norm(L_wr - L_el))
        sleeve_right = float(np.linalg.norm(R_el - R_sh) + np.linalg.norm(R_wr - R_el))
        res["sleeve_len_cm"] = float(np.nanmean([sleeve_left, sleeve_right]) * 100.0)

        # Shoulder width
        res["shoulder_width_cm"] = float(
            np.linalg.norm(joints[mp["left_shoulder"]] - joints[mp["right_shoulder"]]) * 100.0
        )

        # Lengths
        res["top_len_cm"] = float(max(0.0, y_neck - (y_hips_mean + 0.02)) * 100)
        res["gown_len_cm"] = float(max(0.0, y_neck - y_ground) * 100)
        return res

    @staticmethod
    def pretty_farsi(results: dict) -> dict:
        """Convert results to Farsi labels."""
        labels = {
            "chest_circum_cm": "دور سینه",
            "waist_circum_cm": "دور کمر",
            "hip_circum_cm": "دور باسن",
            "upperarm_circum_cm": "دور بازو",
            "thigh_circum_cm": "دور ران",
            "calf_circum_cm": "دور ساق پا",
            "neck_circum_cm": "دور گردن",
            "pants_outseam_cm": "قد بیرونی شلوار",
            "sleeve_len_cm": "قد آستین",
            "top_len_cm": "قد بالاتنه (بلوز)",
            "gown_len_cm": "قد لباس بلند",
            "shoulder_width_cm": "پهنای شانه",
            "user_height_cm": "قد کاربر",
            "scale_factor": "ضریب مقیاس مدل",
            "width_scale": "ضریب پهنای بدن",
            "gender": "جنسیت",
            "age": "سن",
            "body_model": "مدل بدنی",
        }
        output = {}
        for k, label in labels.items():
            if k in results:
                v = results[k]
                if isinstance(v, int) and k in ("age",):
                    output[k] = f"{label}: {v}"
                elif isinstance(v, (int, float)) and np.isfinite(v):
                    unit = "سانتی‌متر" if k.endswith("_cm") else ""
                    output[k] = f"{label}: {v:.1f} {unit}".strip()
                elif isinstance(v, str):
                    output[k] = f"{label}: {v}"
        return output
