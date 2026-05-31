"""
Singleton registry for PARE + SMPL models.

Loads models once at first use and keeps them in GPU memory (or CPU).
Eliminates subprocess overhead by running PARE inference in-process.
"""
import logging
import os
import sys
import threading
from argparse import Namespace
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_PARE_ROOT = Path(__file__).resolve().parent / "PARE" / "scripts"
_CKPT_DIR = _PARE_ROOT / "data" / "pare" / "checkpoints"
_SMPL_DIR = _PARE_ROOT / "data" / "body_models" / "smpl"

_CFG_PATH = _CKPT_DIR / "pare_w_3dpw_config.yaml"
_CKPT_PATH = _CKPT_DIR / "pare_w_3dpw_checkpoint.ckpt"


class ModelRegistry:
    """Lazy-initialised singleton holding PARE tester and SMPL model."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialised = False
        return cls._instance

    # ------------------------------------------------------------------
    # Initialisation (heavy — runs once)
    # ------------------------------------------------------------------
    def _ensure_init(self):
        if self._initialised:
            return

        import torch

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("ModelRegistry: device=%s", self.device)

        # ---- Load PARE tester (includes YOLO detector + PARE model) ----
        self._tester = self._load_pare_tester()

        # ---- Load SMPL for consensus mesh ----
        self._smpl = self._load_smpl()

        # ---- Warm-up ----
        if self.device.type == "cuda":
            self._warmup()

        self._initialised = True
        logger.info("ModelRegistry: all models ready")

    def _load_pare_tester(self):
        """Instantiate PARETester with pre-built args (loads model + detector)."""
        # PARETester expects to run from PARE/scripts/ dir because of relative
        # paths in the config.  We temporarily change cwd.
        original_cwd = os.getcwd()
        pare_scripts = str(_PARE_ROOT)

        # Ensure PARE's parent is on sys.path so imports work
        if pare_scripts not in sys.path:
            sys.path.insert(0, pare_scripts)

        try:
            os.chdir(pare_scripts)
            from pare.core.tester import PARETester

            args = Namespace(
                cfg=str(_CFG_PATH),
                ckpt=str(_CKPT_PATH),
                exp="",
                mode="folder",
                vid_file=None,
                image_folder=None,
                output_folder="",
                tracking_method="bbox",
                detector="yolo",
                yolo_img_size=416,
                tracker_batch_size=1,
                staf_dir="",
                batch_size=16,
                display=False,
                smooth=False,
                min_cutoff=0.004,
                beta=1.0,
                no_render=True,
                no_save=False,
                wireframe=False,
                sideview=False,
                draw_keypoints=False,
                save_obj=False,
                smplify=False,
            )
            tester = PARETester(args)
            logger.info("PARE model loaded in-process on %s", self.device)
            return tester

        finally:
            os.chdir(original_cwd)

    def _load_smpl(self):
        """Load smplx.SMPL model for consensus mesh building."""
        import torch
        from smplx import SMPL

        smpl = SMPL(
            model_path=str(_SMPL_DIR),
            gender="neutral",
            batch_size=1,
        ).to(self.device)
        smpl.eval()
        logger.info("SMPL model loaded on %s", self.device)
        return smpl

    def _warmup(self):
        """Run dummy inference to pre-compile CUDA kernels."""
        import torch

        logger.info("Running warm-up inference…")
        try:
            dummy = torch.zeros(1, 3, 224, 224, device=self.device)
            with torch.no_grad():
                with torch.amp.autocast("cuda"):
                    _ = self._tester.model(dummy)
            del dummy

            betas = torch.zeros(1, 10, device=self.device)
            with torch.no_grad():
                _ = self._smpl(betas=betas)
            del betas

            torch.cuda.empty_cache()
        except Exception as e:
            logger.warning("Warm-up failed (non-fatal): %s", e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run_pare_on_folder(
        self,
        image_folder: str,
        output_folder: str,
    ) -> List[Path]:
        """Run PARE person detection + inference on a folder of images.

        Returns list of per-image pkl paths written by PARETester.
        """
        self._ensure_init()

        original_cwd = os.getcwd()
        pare_scripts = str(_PARE_ROOT)

        try:
            os.chdir(pare_scripts)

            output_path = str(output_folder)
            os.makedirs(output_path, exist_ok=True)
            output_img_folder = os.path.join(output_path, "pare_results")
            os.makedirs(output_img_folder, exist_ok=True)

            # Detect persons
            self._tester.args.tracker_batch_size = 1
            detections = self._tester.run_detector(image_folder)

            # Run inference (with mixed precision on CUDA)
            if self.device.type == "cuda":
                self._run_inference_amp(
                    image_folder, detections, output_path, output_img_folder
                )
            else:
                self._tester.run_on_image_folder(
                    image_folder, detections, output_path, output_img_folder,
                    run_smplify=False,
                )

        finally:
            os.chdir(original_cwd)

        # Collect output pkl files
        out_dir = Path(output_folder) / "pare_results"
        pkls = sorted(out_dir.glob("*.pkl")) if out_dir.exists() else []
        logger.info("PARE produced %d result files", len(pkls))
        return pkls

    def _run_inference_amp(
        self, image_folder, detections, output_path, output_img_folder
    ):
        """Run PARE folder inference with AMP (mixed precision)."""
        import copy
        import cv2
        import torch
        import joblib

        from pare.utils.vibe_image_utils import get_single_image_crop_demo
        from pare.utils.demo_utils import (
            convert_crop_cam_to_orig_img,
            convert_crop_coords_to_orig_img,
        )

        image_file_names = sorted([
            os.path.join(image_folder, x)
            for x in os.listdir(image_folder)
            if x.lower().endswith(('.jpg', '.png', '.jpeg'))
        ])

        for img_idx, img_fname in enumerate(image_file_names):
            dets = detections[img_idx]
            if len(dets) < 1:
                continue

            img = cv2.cvtColor(cv2.imread(img_fname), cv2.COLOR_BGR2RGB)
            orig_height, orig_width = img.shape[:2]

            inp_images = torch.zeros(
                len(dets), 3,
                self._tester.model_cfg.DATASET.IMG_RES,
                self._tester.model_cfg.DATASET.IMG_RES,
                device=self.device, dtype=torch.float,
            )

            for det_idx, det in enumerate(dets):
                norm_img, raw_img, kp_2d = get_single_image_crop_demo(
                    img, det, kp_2d=None, scale=1.0,
                    crop_size=self._tester.model_cfg.DATASET.IMG_RES,
                )
                inp_images[det_idx] = norm_img.float().to(self.device)

            # Mixed-precision forward pass
            with torch.no_grad():
                if self.device.type == "cuda":
                    with torch.amp.autocast("cuda"):
                        output = self._tester.model(inp_images)
                else:
                    output = self._tester.model(inp_images)

            for k, v in output.items():
                output[k] = v.cpu().numpy()

            orig_cam = convert_crop_cam_to_orig_img(
                cam=output['pred_cam'],
                bbox=dets,
                img_width=orig_width,
                img_height=orig_height,
            )
            smpl_joints2d = convert_crop_coords_to_orig_img(
                bbox=dets,
                keypoints=output['smpl_joints2d'],
                crop_size=self._tester.model_cfg.DATASET.IMG_RES,
            )
            output['bboxes'] = dets
            output['orig_cam'] = orig_cam
            output['smpl_joints2d'] = smpl_joints2d

            del inp_images

            save_f = os.path.join(
                output_path, 'pare_results',
                os.path.basename(img_fname).replace(
                    img_fname.split('.')[-1], 'pkl'
                ),
            )
            joblib.dump(output, save_f)

        if self.device.type == "cuda":
            torch.cuda.empty_cache()

    def extract_view_data(self, pkl_paths: List[Path]) -> Dict[str, dict]:
        """Parse PARE per-image pkl files into view data dicts.

        Returns dict of view_name → {vertices, joints, betas, pose}.
        """
        import joblib

        views = {}
        for pkl_path in pkl_paths:
            fname = pkl_path.stem.lower()
            view_name = next(
                (k for k in ("front_a", "side", "back_a", "front_t") if k in fname),
                fname,
            )
            try:
                data = joblib.load(str(pkl_path))
                # Take first detection per image
                verts = np.asarray(data.get("smpl_vertices", data.get("vertices")))
                joints = np.asarray(data.get("smpl_joints3d", data.get("joints3d")))
                betas = np.asarray(data.get("pred_shape", data.get("betas")))
                pose = np.asarray(data.get("pred_pose", data.get("pose")))

                # If batched (N, ...), take first
                if verts.ndim == 3:
                    verts = verts[0]
                if joints.ndim == 3:
                    joints = joints[0]
                if betas.ndim == 2:
                    betas = betas[0]
                if pose.ndim >= 2:
                    pose = pose[0]

                views[view_name] = {
                    "vertices": verts,
                    "joints": joints,
                    "betas": betas,
                    "pose": pose,
                }
            except Exception as e:
                logger.warning("Failed to parse %s: %s", pkl_path, e)

        return views

    def build_consensus_mesh(
        self, consensus_betas: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """SMPL forward pass using the cached SMPL model."""
        self._ensure_init()

        import torch
        from measure.consensus_mesh import CANONICAL_APOSE

        betas_t = torch.tensor(
            consensus_betas, dtype=torch.float32
        ).unsqueeze(0).to(self.device)
        pose_t = torch.tensor(
            CANONICAL_APOSE, dtype=torch.float32
        ).unsqueeze(0).to(self.device)

        with torch.no_grad():
            output = self._smpl(
                betas=betas_t,
                body_pose=pose_t[:, 3:],
                global_orient=pose_t[:, :3],
            )

        vertices = output.vertices[0].cpu().numpy()
        joints = output.joints[0].cpu().numpy()

        del betas_t, pose_t, output
        if self.device.type == "cuda":
            torch.cuda.empty_cache()

        return vertices, joints

    @property
    def device_name(self) -> str:
        self._ensure_init()
        return str(self.device)


def get_registry() -> ModelRegistry:
    """Get or create the global ModelRegistry singleton."""
    return ModelRegistry()
