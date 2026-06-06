"""
Body silhouette rendering from measurements.
"""
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")  # non-GUI backend — prevents Tkinter errors in server
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon


class BodySilhouetteRenderer:
    """
    Convert measurement results to a 2D silhouette (front view) and save as PNG/SVG.
    """

    def __init__(self, out_dir: Path, dpi: int = 150, color="#2b6cb0"):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.dpi = dpi
        self.color = color

    @staticmethod
    def _half_width_from_circumference(
        C: Optional[float],
        depth_ratio: float = 0.8
    ) -> Optional[float]:
        """
        Approximate ellipse half-width from circumference.
        Uses Ramanujan approximation.
        """
        if not C or C <= 0:
            return None
        r = float(max(0.55, min(1.10, depth_ratio)))
        K = (3 * (1 + r) - np.sqrt((3 + r) * (1 + 3 * r)))
        if K <= 1e-6:
            return None
        a = C / (np.pi * K)
        return float(a)

    def _key_widths(self, measures: Dict) -> Dict[str, float]:
        """Extract key widths from measurements."""
        # Support both nested format (from MediaPipe) and flat format (from BodyMeasurement)
        circ = measures.get("circumferences_cm", {}) or {}

        # Depth ratios for ellipse approximation
        r_chest = 0.85
        r_waist = 0.80
        r_hip = 0.85
        r_thigh = 0.95

        # Try nested format first, then flat format
        chest_val = circ.get("chest") or measures.get("chest_circum_cm")
        waist_val = circ.get("waist") or measures.get("waist_circum_cm")
        hip_val = circ.get("hip") or measures.get("hip_circum_cm")
        thigh_val = circ.get("thigh") or measures.get("thigh_circum_cm")

        chest_a = self._half_width_from_circumference(chest_val, r_chest) or 20
        waist_a = self._half_width_from_circumference(waist_val, r_waist) or 18
        hip_a = self._half_width_from_circumference(hip_val, r_hip) or 22
        thigh_a = self._half_width_from_circumference(thigh_val, r_thigh) or 10

        return {
            "chest": chest_a,
            "waist": waist_a,
            "hip": hip_a,
            "thigh": thigh_a,
        }

    def _key_heights(self, measures: Dict) -> Dict[str, float]:
        """Extract key heights from measurements."""
        # Support both nested format (from MediaPipe) and flat format (from BodyMeasurement)
        L = measures.get("lengths_cm", {}) or {}

        # Try nested format first, then flat format
        top_len = L.get("top_from_neck_hollow_to_hip") or measures.get("top_len_cm") or 60.0
        dress_len = L.get("dress_from_neck_hollow_to_floor") or measures.get("gown_len_cm") or 110.0
        user_height = measures.get("user_height_cm", 175.0)

        # Use user height to estimate total if dress_len seems too short
        torso_h = max(35.0, float(top_len))
        total_h = max(torso_h + 40.0, float(dress_len), float(user_height) * 0.65)

        # Key vertical levels (z=0 at neck)
        z_neck = 0.0
        z_chest = torso_h * 0.55
        z_waist = torso_h * 0.85
        z_hip = torso_h * 1.00
        z_thigh = z_hip + (total_h - torso_h) * 0.28
        z_knee = z_hip + (total_h - torso_h) * 0.60
        z_ankle = total_h * 0.98

        return {
            "neck": z_neck,
            "chest": z_chest,
            "waist": z_waist,
            "hip": z_hip,
            "thigh": z_thigh,
            "knee": z_knee,
            "ankle": z_ankle,
            "total": total_h,
        }

    def _profile_points(
        self,
        widths: Dict[str, float],
        heights: Dict[str, float]
    ) -> np.ndarray:
        """Generate half-profile points for body silhouette."""
        # Half-widths
        a_neck = max(widths["chest"] * 0.55, 7.0)
        a_chest = widths["chest"]
        a_waist = widths["waist"]
        a_hip = widths["hip"]
        a_thigh = widths["thigh"]
        a_knee = max(a_thigh * 0.65, 5.0)
        a_ankle = max(a_thigh * 0.35, 3.0)

        # Heights
        z = heights

        # Key points for right half (x >= 0)
        key = [
            (a_neck, z["neck"]),
            (a_chest, z["chest"]),
            (a_waist, z["waist"]),
            (a_hip, z["hip"]),
            (a_thigh, z["thigh"]),
            (a_knee, z["knee"]),
            (a_ankle, z["ankle"]),
        ]

        # Interpolate for smooth curves
        def interp(p1, p2, k=6):
            (x1, z1), (x2, z2) = p1, p2
            ts = np.linspace(0, 1, k, endpoint=False)[1:]
            return [(x1 * (1 - t) + x2 * t, z1 * (1 - t) + z2 * t) for t in ts]

        pts_right = []
        for i in range(len(key) - 1):
            pts_right.append(key[i])
            pts_right += interp(key[i], key[i + 1], k=8)
        pts_right.append(key[-1])

        # Mirror for left half
        pts_left = [(-x, z) for (x, z) in reversed(pts_right)]

        # Close polygon
        poly = np.array(pts_right + pts_left, dtype=float)
        return poly

    def render(
        self,
        measures: Dict,
        file_name: str = "silhouette.png",
        show: bool = False
    ) -> str:
        """Render silhouette and save to file."""
        widths = self._key_widths(measures)
        heights = self._key_heights(measures)
        poly_xz = self._profile_points(widths, heights)

        # Convert to image coordinates
        x = poly_xz[:, 0]
        z = poly_xz[:, 1]
        H = heights["total"]
        y_img = H - z

        fig, ax = plt.subplots(figsize=(4, 8))

        # Filled polygon
        verts = np.column_stack([x, y_img])
        patch = Polygon(
            verts, closed=True,
            facecolor=self.color,
            edgecolor="black",
            linewidth=1.0,
            alpha=0.9
        )
        ax.add_patch(patch)

        # Frame and aspect ratio
        pad = max(8.0, widths["hip"] * 0.6)
        ax.set_xlim(-widths["hip"] - pad, widths["hip"] + pad)
        ax.set_ylim(H + 10, -10)
        ax.set_aspect("equal", adjustable="box")
        ax.axis("off")

        self.out_dir.mkdir(parents=True, exist_ok=True)
        out_path = (self.out_dir / file_name).as_posix()
        plt.savefig(out_path, dpi=self.dpi, bbox_inches="tight", transparent=True)
        if show:
            plt.show()
        plt.close(fig)
        return out_path
