"""
Silhouette vs mesh projection comparison.

Projects the consensus SMPL mesh onto the image plane for each view,
then compares the projected silhouette against the MediaPipe body
segmentation mask.  Returns an IoU-based similarity score per view.
"""
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _project_mesh_silhouette(
    vertices: np.ndarray,
    img_h: int,
    img_w: int,
) -> np.ndarray:
    """Weak-perspective projection of mesh vertices onto image plane.

    Assumes the mesh is roughly centred and uses a simple orthographic
    projection (XZ → pixel coords) scaled to fill the image.

    Returns a binary mask (img_h, img_w) of dtype uint8.
    """
    x = vertices[:, 0]
    y = vertices[:, 1]

    # Normalise to [0, 1]
    x_min, x_max = x.min(), x.max()
    y_min, y_max = y.min(), y.max()
    x_range = max(x_max - x_min, 1e-6)
    y_range = max(y_max - y_min, 1e-6)

    # Preserve aspect ratio
    scale = min(img_w / x_range, img_h / y_range) * 0.85
    cx = img_w / 2.0
    cy = img_h / 2.0
    mx = (x_min + x_max) / 2.0
    my = (y_min + y_max) / 2.0

    px = ((x - mx) * scale + cx).astype(np.int32)
    # Y axis is inverted (image top = 0, mesh top = max Y)
    py = (-(y - my) * scale + cy).astype(np.int32)

    # Clip to image bounds
    px = np.clip(px, 0, img_w - 1)
    py = np.clip(py, 0, img_h - 1)

    mask = np.zeros((img_h, img_w), dtype=np.uint8)
    mask[py, px] = 255

    # Dilate to fill gaps between sparse vertices
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.dilate(mask, kernel, iterations=2)

    # Fill the interior via flood-fill from corners (background)
    filled = mask.copy()
    flood = np.zeros((img_h + 2, img_w + 2), dtype=np.uint8)
    cv2.floodFill(filled, flood, (0, 0), 255)
    filled_inv = cv2.bitwise_not(filled)
    mask = mask | filled_inv

    return mask


_SEGMENTER_MODEL_PATH = Path(__file__).resolve().parent / "data" / "selfie_segmenter.tflite"


def _body_mask_mediapipe(image_bgr: np.ndarray) -> Optional[np.ndarray]:
    """Extract body segmentation mask using MediaPipe ImageSegmenter (Tasks API).

    Returns a binary mask (H, W) of dtype uint8, or None on failure.
    """
    try:
        import mediapipe as mp_lib
        from mediapipe.tasks.python import BaseOptions, vision

        if not _SEGMENTER_MODEL_PATH.exists():
            logger.debug("Segmenter model not found — skipping silhouette mask")
            return None

        options = vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=str(_SEGMENTER_MODEL_PATH)),
            output_confidence_masks=True,
            output_category_mask=False,
        )
        segmenter = vision.ImageSegmenter.create_from_options(options)

        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp_lib.Image(
            image_format=mp_lib.ImageFormat.SRGB,
            data=rgb,
        )
        result = segmenter.segment(mp_image)
        segmenter.close()

        if not result.confidence_masks or len(result.confidence_masks) == 0:
            return None

        conf_mask = result.confidence_masks[0].numpy_view()
        mask = (conf_mask > 0.5).astype(np.uint8) * 255
        return mask
    except Exception as e:
        logger.warning(f"MediaPipe segmentation failed: {e}")
        return None


def compute_silhouette_iou(
    mesh_mask: np.ndarray,
    body_mask: np.ndarray,
) -> float:
    """Intersection over Union of two binary masks."""
    m1 = mesh_mask > 127
    m2 = body_mask > 127
    intersection = np.logical_and(m1, m2).sum()
    union = np.logical_or(m1, m2).sum()
    if union == 0:
        return 0.0
    return float(intersection / union)


def compare_silhouettes(
    vertices: np.ndarray,
    image_paths: Dict[str, str],
) -> Dict[str, float]:
    """Compare projected mesh silhouette against body segmentation per view.

    Parameters
    ----------
    vertices : (6890, 3) array
        Consensus mesh vertices (scaled to real height).
    image_paths : dict
        Mapping view_name → image file path.

    Returns
    -------
    dict
        Mapping view_name → IoU similarity score [0, 1].
    """
    scores = {}
    for view_name, img_path in image_paths.items():
        try:
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            h, w = img.shape[:2]

            mesh_mask = _project_mesh_silhouette(vertices, h, w)
            body_mask = _body_mask_mediapipe(img)
            if body_mask is None:
                continue

            iou = compute_silhouette_iou(mesh_mask, body_mask)
            scores[view_name] = iou
            logger.info(f"Silhouette IoU for {view_name}: {iou:.3f}")
        except Exception as e:
            logger.warning(f"Silhouette comparison failed for {view_name}: {e}")

    return scores
