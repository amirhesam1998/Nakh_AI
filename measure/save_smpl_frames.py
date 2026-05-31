"""
SMPL frame extraction from PARE output.
"""
import os
import logging
from typing import List

import joblib
import numpy as np

logger = logging.getLogger(__name__)


class SMPLExtractor:
    """Extract SMPL frames from PARE pickle output.

    The PARE pickle holds one SMPL fit per video frame. Frames are emitted to
    NPZ files in the *order they appeared in the source video* — the labels
    "front"/"tpose"/"side" reflect the order the user uploaded photos in, not
    a runtime pose detection. Callers must keep upload order stable for
    downstream labels to be meaningful.
    """

    def __init__(self, pkl_path: str, frame_names=None):
        self.pkl_path = os.path.abspath(pkl_path)
        self.out_dir = os.path.dirname(self.pkl_path)
        self.frame_names = list(frame_names) if frame_names else [
            'tmp_front_smpl.npz',
            'tmp_tpose_smpl.npz',
            'tmp_side_smpl.npz',
        ]

    def _load_data(self):
        """Load data from pickle file."""
        if not os.path.exists(self.pkl_path):
            raise FileNotFoundError(f"File not found: {self.pkl_path}")

        logger.info(f"Loading: {self.pkl_path}")
        data = joblib.load(self.pkl_path)

        if not isinstance(data, dict) or not data:
            raise ValueError("Invalid or empty data format!")

        # Assume only one person detected in video
        track_id = sorted(data.keys())[0]
        track_data = data[track_id]

        # Check required keys
        required_keys = ['verts', 'joints3d', 'pose', 'betas']
        for k in required_keys:
            if k not in track_data:
                raise KeyError(f"Key '{k}' not found in data.")

        verts = np.asarray(track_data['verts'])
        joints = np.asarray(track_data['joints3d'])
        pose = np.asarray(track_data['pose'])
        betas = np.asarray(track_data['betas'])

        if len(verts) < 3:
            raise ValueError("Less than 3 frames in video!")

        logger.info(f"Loaded frames: {len(verts)}")
        return verts, joints, pose, betas

    def _save_frame(
        self,
        i: int,
        verts: np.ndarray,
        joints: np.ndarray,
        pose: np.ndarray,
        betas: np.ndarray,
        name: str
    ) -> str:
        """Save specific frame as npz."""
        path = os.path.join(self.out_dir, name)
        np.savez(path, vertices=verts[i], joints=joints[i], pose=pose[i], betas=betas[i])
        logger.info(f"Wrote: {path}")
        return path

    def extract_and_save(self) -> List[str]:
        """Execute extraction and save process.

        If PARE produced fewer frames than the configured frame_names, only
        the available frames are written and a warning is logged so the
        caller can correlate missing views with downstream measurement gaps.
        """
        verts, joints, pose, betas = self._load_data()
        out_files = []

        n_frames = len(verts)
        n_targets = len(self.frame_names)
        if n_frames < n_targets:
            logger.warning(
                "PARE produced %d frame(s) but %d pose label(s) are configured "
                "(%s). Saving only the available frames.",
                n_frames, n_targets, self.frame_names,
            )

        for i in range(min(n_frames, n_targets)):
            path = self._save_frame(i, verts, joints, pose, betas, self.frame_names[i])
            out_files.append(path)

        logger.info(f"Done. Saved: {out_files}")
        return out_files
