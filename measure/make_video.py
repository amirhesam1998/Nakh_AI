"""
Video creation from image sequences.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Literal, Optional, Tuple
import cv2
import os
import glob

SortBy = Literal["name", "mtime"]
ResizeMode = Literal["stretch", "fit", "cover"]


@dataclass
class MakeVideo:
    """Create video from image sequence."""

    img_dir: Optional[Path] = None
    output: Path = Path("out.mp4")
    fps: int = 1
    pattern: str = "*.jpg;*.jpeg;*.png"
    min_images: int = 3
    codec: str = "mp4v"
    sort_by: SortBy = "name"
    size: Optional[Tuple[int, int]] = None
    resize_mode: ResizeMode = "stretch"
    overwrite: bool = True

    def _collect_images(self) -> List[Path]:
        """Collect images from directory."""
        if self.img_dir is None:
            raise ValueError("img_dir is not specified.")

        exts = [p.strip() for p in self.pattern.split(";") if p.strip()]
        paths: List[str] = []
        for ext in exts:
            paths.extend(glob.glob(os.path.join(str(self.img_dir), ext)))
        imgs = [Path(p) for p in paths if p.lower().endswith((".jpg", ".jpeg", ".png"))]

        if self.sort_by == "name":
            imgs.sort(key=lambda p: p.name.lower())
        else:
            imgs.sort(key=lambda p: p.stat().st_mtime)

        if len(imgs) < self.min_images:
            raise ValueError(f"At least {self.min_images} images required, found {len(imgs)}.")

        return imgs

    @staticmethod
    def _ensure_bgr(img_path: Path):
        """Load image as BGR."""
        im = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        if im is None:
            raise ValueError(f"Failed to read image: {img_path}")
        return im

    @staticmethod
    def _letterbox(im, target_w: int, target_h: int, mode: ResizeMode):
        """Resize image with letterbox/cover mode."""
        h, w = im.shape[:2]
        if mode == "stretch":
            return cv2.resize(im, (target_w, target_h), interpolation=cv2.INTER_AREA)

        src_aspect = w / h
        dst_aspect = target_w / target_h

        if mode == "fit":
            if src_aspect > dst_aspect:
                new_w = target_w
                new_h = int(round(new_w / src_aspect))
            else:
                new_h = target_h
                new_w = int(round(new_h * src_aspect))
            resized = cv2.resize(im, (new_w, new_h), interpolation=cv2.INTER_AREA)

            top = (target_h - new_h) // 2
            bottom = target_h - new_h - top
            left = (target_w - new_w) // 2
            right = target_w - new_w - left
            return cv2.copyMakeBorder(
                resized, top, bottom, left, right,
                borderType=cv2.BORDER_CONSTANT, value=(0, 0, 0)
            )

        if mode == "cover":
            if src_aspect < dst_aspect:
                new_w = target_w
                new_h = int(round(new_w / src_aspect))
            else:
                new_h = target_h
                new_w = int(round(new_h * src_aspect))
            resized = cv2.resize(im, (new_w, new_h), interpolation=cv2.INTER_AREA)
            x1 = (new_w - target_w) // 2
            y1 = (new_h - target_h) // 2
            return resized[y1:y1 + target_h, x1:x1 + target_w]

        return cv2.resize(im, (target_w, target_h), interpolation=cv2.INTER_AREA)

    def make_from_dir(self) -> Tuple[Path, int]:
        """Create video from images in directory."""
        imgs = self._collect_images()
        return self.make_from_images(imgs)

    def make_from_images(self, images: Iterable[Path]) -> Tuple[Path, int]:
        """Create video from list of image paths."""
        images = list(images)
        if len(images) < self.min_images:
            raise ValueError(f"At least {self.min_images} images required.")

        if self.size is None:
            first = self._ensure_bgr(images[0])
            h, w = first.shape[:2]
            frame_size = (w, h)
        else:
            frame_size = self.size
            first = self._letterbox(
                self._ensure_bgr(images[0]),
                frame_size[0], frame_size[1],
                self.resize_mode
            )

        if self.output.exists() and not self.overwrite:
            raise FileExistsError(f"Output file exists: {self.output}")

        self.output.parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        writer = cv2.VideoWriter(str(self.output), fourcc, float(self.fps), frame_size)

        count = 0
        try:
            if self.size is None:
                writer.write(first)
                count += 1

                for p in images[1:]:
                    im = self._ensure_bgr(p)
                    if im.shape[1] != frame_size[0] or im.shape[0] != frame_size[1]:
                        im = self._letterbox(im, frame_size[0], frame_size[1], self.resize_mode)
                    writer.write(im)
                    count += 1
            else:
                for p in images:
                    im = self._ensure_bgr(p)
                    im = self._letterbox(im, frame_size[0], frame_size[1], self.resize_mode)
                    writer.write(im)
                    count += 1
        finally:
            writer.release()

        return self.output, count

    @classmethod
    def quick(
        cls,
        img_dir: Path,
        output: Path,
        fps: int = 1,
        pattern: str = "*.jpg;*.jpeg;*.png",
        resize_mode: ResizeMode = "stretch"
    ) -> Tuple[Path, int]:
        """Quick video creation from directory."""
        mv = cls(
            img_dir=img_dir,
            output=output,
            fps=fps,
            pattern=pattern,
            resize_mode=resize_mode
        )
        return mv.make_from_dir()
