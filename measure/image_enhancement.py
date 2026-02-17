"""
Image enhancement and processing utilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union
from io import BytesIO
from pathlib import Path
import math

import numpy as np
import cv2
from PIL import Image, ImageOps, ImageCms, UnidentifiedImageError
import pillow_heif


@dataclass
class UprightMeta:
    """Metadata for image upright correction."""
    roll_deg: float
    shear_shx: float


class ImageToolkit:
    """Image processing toolkit for enhancement and conversion."""

    def __init__(
        self,
        bg_color: Tuple[int, int, int] = (255, 255, 255),
        force_srgb: bool = True
    ):
        pillow_heif.register_heif_opener()
        self.bg_color = bg_color
        self.force_srgb = force_srgb

    def convert_pilImage_to_rgb(self, pilImage: Image.Image) -> np.ndarray:
        """Convert PIL Image to RGB numpy array."""
        img_exif = ImageOps.exif_transpose(pilImage)

        if self.force_srgb:
            try:
                icc = img_exif.info.get("icc_profile")
                if icc:
                    srgb = ImageCms.createProfile("sRGB")
                    in_prof = ImageCms.ImageCmsProfile(BytesIO(icc))
                    img_exif = ImageCms.profileToProfile(
                        img_exif, in_prof, srgb, outputMode=img_exif.mode
                    )
            except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
                pass

        if img_exif.mode in ("RGBA", "LA"):
            base = Image.new("RGB", img_exif.size, self.bg_color)
            base.paste(img_exif, mask=img_exif.split()[-1])
            img_exif = base
        if img_exif.mode != "RGB":
            img_exif = img_exif.convert("RGB")
        return np.array(img_exif)

    def load_rgb(self, src: Union[str, Path]) -> np.ndarray:
        """Load image as RGB numpy array."""
        img_path = Path(src)
        if not img_path.exists():
            raise FileNotFoundError(f"File not found: {img_path.resolve()}")

        img_bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        if img_bgr is not None:
            return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        try:
            return self.convert_pilImage_to_rgb(Image.open(img_path))
        except (UnidentifiedImageError, OSError) as e:
            raise ValueError(f"Cannot read: {img_path.name} | {e}")

    def save_jpeg(
        self,
        rgb: np.ndarray,
        out_path: Union[str, Path],
        quality: int = 95
    ) -> str:
        """Save RGB array as JPEG."""
        out = str(out_path)
        ok = cv2.imwrite(
            out,
            cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
            [cv2.IMWRITE_JPEG_QUALITY, int(quality)]
        )
        if not ok:
            raise RuntimeError("JPEG save failed.")
        return out

    def convert_file_to_jpeg(
        self,
        file: Union[str, Path],
        quality: int = 95
    ) -> str:
        """Convert image file to JPEG format."""
        img_path = Path(file)
        if img_path.suffix.lower() in (".jpg", ".jpeg"):
            return str(img_path)
        img_rgb = self.load_rgb(img_path)
        img_out = img_path.with_suffix(".jpg")
        return self.save_jpeg(img_rgb, img_out, quality=quality)

    @staticmethod
    def assess_contrast(img_rgb: np.ndarray) -> dict:
        """Assess image contrast."""
        y = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2YCrCb)[:, :, 0].astype(np.float32)
        p1, p99 = np.percentile(y, 1), np.percentile(y, 99)
        return {
            "dynamic_range": float(max(0.0, (p99 - p1) / 255.0)),
            "contrast_std": float(y.std() / 255.0),
            "mean_y": float(y.mean()),
        }

    @staticmethod
    def _clahe_on_y(img_bgr: np.ndarray, dyn: float, std: float):
        """Apply CLAHE on Y channel."""
        ycrcb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)
        y, cr, cb = cv2.split(ycrcb)
        clip, grid = 2.0, (8, 8)
        if dyn < 0.55 or std < 0.10:
            clip, grid = 3.0, (8, 8)
        if dyn < 0.40 or std < 0.07:
            clip, grid = 3.5, (6, 6)
        clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=grid)
        y_eq = clahe.apply(y)
        return cv2.cvtColor(cv2.merge([y_eq, cr, cb]), cv2.COLOR_YCrCb2BGR), clip, grid

    @staticmethod
    def _adaptive_gamma(img_bgr: np.ndarray, target_mean: float):
        """Apply adaptive gamma correction."""
        y = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)[:, :, 0].astype(np.float32)
        mean_norm = max(1e-3, float(y.mean() / 255.0))
        target_norm = target_mean / 255.0
        gamma = float(np.clip(math.log(target_norm) / math.log(mean_norm), 0.7, 1.5))
        if abs(gamma - 1.0) <= 0.05:
            return img_bgr, gamma
        inv = 1.0 / gamma
        lut = np.array([((i / 255.0) ** inv) * 255.0 for i in range(256)]).astype("uint8")
        return cv2.LUT(img_bgr, lut), gamma

    def enhance_contrast(self, img_rgb: np.ndarray, target_mean: float = 135.0):
        """Enhance image contrast."""
        before = self.assess_contrast(img_rgb)
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        img_bgr, clip, grid = self._clahe_on_y(img_bgr, before["dynamic_range"], before["contrast_std"])
        img_bgr, gamma = self._adaptive_gamma(img_bgr, target_mean=target_mean)

        img_bgr = cv2.bilateralFilter(img_bgr, d=5, sigmaColor=50, sigmaSpace=50)
        blur = cv2.GaussianBlur(img_bgr, (0, 0), sigmaX=1.0)
        img_bgr = cv2.addWeighted(img_bgr, 1.08, blur, -0.08, 0)

        rgb_out = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        after = self.assess_contrast(rgb_out)
        meta = {"clahe": f"{clip}/{grid}", "gamma": round(gamma, 2)}
        return rgb_out, before, after, meta

    @staticmethod
    def measure_sharpness(rgb: np.ndarray) -> float:
        """Measure image sharpness."""
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    @staticmethod
    def sharpen_image(rgb: np.ndarray, amount: float = 1.2, radius: float = 1.2) -> np.ndarray:
        """Sharpen image."""
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        blur = cv2.GaussianBlur(bgr, (0, 0), sigmaX=radius)
        sharp = cv2.addWeighted(bgr, 1.0 + amount, blur, -amount, 0)
        return cv2.cvtColor(sharp, cv2.COLOR_BGR2RGB)

    @staticmethod
    def estimate_noise_sigma(rgb: np.ndarray, sigma_blur: float = 1.0) -> float:
        """Estimate noise sigma."""
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        blur = cv2.GaussianBlur(gray, (0, 0), sigmaX=sigma_blur)
        resid = gray - blur
        med = np.median(resid)
        mad = np.median(np.abs(resid - med))
        return float(1.4826 * mad)

    @staticmethod
    def _fastnl_h_from_sigma(sigma: float):
        """Get denoising parameters from noise sigma."""
        if sigma < 5:
            return 0, 0
        if sigma < 12:
            return 6, 4
        if sigma < 20:
            return 10, 7
        return 14, 10

    def denoise_adaptive(self, rgb: np.ndarray, sigma: float):
        """Apply adaptive denoising."""
        h_l, h_c = self._fastnl_h_from_sigma(sigma)
        if h_l == 0 and h_c == 0:
            return rgb, {"method": "none"}
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        den = cv2.fastNlMeansDenoisingColored(
            bgr, None, h=h_l, hColor=h_c,
            templateWindowSize=7, searchWindowSize=21
        )
        blur = cv2.GaussianBlur(den, (0, 0), sigmaX=0.8)
        den_sharp = cv2.addWeighted(den, 1.08, blur, -0.08, 0)
        meta = {"method": "fastNlMeansDenoisingColored", "h": h_l, "hColor": h_c}
        return cv2.cvtColor(den_sharp, cv2.COLOR_BGR2RGB), meta

    @staticmethod
    def _detect_lines(rgb: np.ndarray, canny1=50, canny2=150, min_line_len_ratio=0.2, max_line_gap=10):
        """Detect lines in image."""
        h, w = rgb.shape[:2]
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        g = cv2.GaussianBlur(g, (5, 5), 0)
        edges = cv2.Canny(g, canny1, canny2, L2gradient=True)
        min_line_len = int(min(h, w) * min_line_len_ratio)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, threshold=80,
            minLineLength=min_line_len, maxLineGap=max_line_gap
        )
        return [] if lines is None else lines.reshape(-1, 4)

    @staticmethod
    def _line_angle_deg(x1, y1, x2, y2):
        """Calculate line angle in degrees."""
        return np.degrees(np.arctan2((y2 - y1), (x2 - x1)))

    @staticmethod
    def _robust_mean(arr: np.ndarray, pct=15) -> float:
        """Calculate robust mean."""
        if len(arr) == 0:
            return 0.0
        ql, qh = np.percentile(arr, pct), np.percentile(arr, 100 - pct)
        sel = arr[(arr >= ql) & (arr <= qh)]
        return float(sel.mean()) if len(sel) else float(np.mean(arr))

    def _rotate_same_size(self, rgb: np.ndarray, angle_deg: float) -> np.ndarray:
        """Rotate image keeping same size."""
        h, w = rgb.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
        return cv2.warpAffine(rgb, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    @staticmethod
    def _crop_center(im: np.ndarray, w: int, h: int) -> np.ndarray:
        """Crop center of image."""
        hh, ww = im.shape[:2]
        x1 = max(0, (ww - w) // 2)
        y1 = max(0, (hh - h) // 2)
        return im[y1:y1 + h, x1:x1 + w]

    def _apply_horizontal_shear_keep_size(self, rgb: np.ndarray, shx: float) -> np.ndarray:
        """Apply horizontal shear keeping size."""
        h, w = rgb.shape[:2]
        M = np.array([[1, shx, 0], [0, 1, 0]], dtype=np.float32)
        new_w = int(w + abs(shx) * h)
        sheared = cv2.warpAffine(rgb, M, (new_w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        if new_w == w:
            return sheared
        return self._crop_center(sheared, w, h)

    def _estimate_roll(self, rgb: np.ndarray, deg_limit=15) -> float:
        """Estimate roll angle."""
        lines = self._detect_lines(rgb)
        if not len(lines):
            return 0.0
        angs = []
        for x1, y1, x2, y2 in lines:
            a = self._line_angle_deg(x1, y1, x2, y2)
            a = ((a + 90) % 180) - 90
            if abs(a) <= 45:
                angs.append(a)
        if not angs:
            return 0.0
        roll = self._robust_mean(np.array(angs, np.float32), pct=15)
        roll = float(np.clip(roll, -deg_limit, deg_limit))
        return -roll

    def _estimate_vertical_shear(self, rgb: np.ndarray, shear_limit=0.25) -> float:
        """Estimate vertical shear."""
        lines = self._detect_lines(rgb)
        if not len(lines):
            return 0.0
        slopes = []
        for x1, y1, x2, y2 in lines:
            dx, dy = (x2 - x1), (y2 - y1)
            if abs(dy) < 1:
                continue
            ang = self._line_angle_deg(x1, y1, x2, y2)
            if abs(abs(ang) - 90) < 30:
                slopes.append(dx / dy)
        if not slopes:
            return 0.0
        m = self._robust_mean(np.array(slopes, np.float32), pct=15)
        shx = -float(m)
        return float(np.clip(shx, -shear_limit, shear_limit))

    def auto_upright(
        self,
        rgb: np.ndarray,
        roll_limit: float = 15.0,
        shear_limit: float = 0.25,
        keep_size: bool = True
    ):
        """Automatically upright image."""
        roll = self._estimate_roll(rgb, deg_limit=roll_limit)
        rgb_rot = self._rotate_same_size(rgb, roll) if abs(roll) > 0.1 else rgb.copy()

        shx = self._estimate_vertical_shear(rgb_rot, shear_limit=shear_limit)
        if abs(shx) > 1e-3:
            rgb_shear = self._apply_horizontal_shear_keep_size(rgb_rot, shx)
        else:
            rgb_shear = rgb_rot

        return rgb_shear, UprightMeta(roll_deg=round(roll, 2), shear_shx=round(shx, 4))

    def run_file(
        self,
        src_path: Union[str, Path],
        out_dir: Union[str, Path],
        quality: int = 95
    ) -> dict:
        """Process a single image file."""
        src_path = Path(src_path)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        jpg_path = Path(self.convert_file_to_jpeg(src_path))
        img_rgb = self.load_rgb(jpg_path)

        enhanced, before, after, meta = self.enhance_contrast(img_rgb, target_mean=135)

        sharp = self.measure_sharpness(enhanced)
        if sharp < 120:
            enhanced = self.sharpen_image(enhanced, amount=1.2, radius=1.2)

        sigma = self.estimate_noise_sigma(enhanced, sigma_blur=1.0)
        if sigma >= 12:
            enhanced, _ = self.denoise_adaptive(enhanced, sigma)

        upright, meta_u = self.auto_upright(enhanced, keep_size=True)

        assert upright.shape[:2] == img_rgb.shape[:2], "Image dimensions should not change."

        out_name = f"{jpg_path.stem}_processed.jpg"
        out_path = out_dir / out_name
        self.save_jpeg(upright, out_path, quality=quality)

        return {
            "src": str(src_path),
            "jpg": str(jpg_path),
            "out": str(out_path),
            "meta": {
                "contrast_before": before,
                "contrast_after": after,
                "enhance_meta": meta,
                "upright_meta": {"roll_deg": meta_u.roll_deg, "shear_shx": meta_u.shear_shx},
                "sharp": sharp,
                "sigma": sigma,
                "size": {"w": img_rgb.shape[1], "h": img_rgb.shape[0]},
            }
        }
