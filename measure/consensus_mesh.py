"""
Consensus SMPL mesh construction from multi-view PARE outputs.

Fuses per-view shape betas (weighted by quality) into a single body shape,
then runs an SMPL forward pass in a canonical A-pose to produce a unified
mesh for measurement extraction.
"""
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical A-pose definition (SMPL 72-dim axis-angle)
# ---------------------------------------------------------------------------
# Default SMPL pose is T-pose. We rotate shoulders down ~30° and legs
# apart ~10° so that arms separate from torso for clean cross-sections
# while keeping a natural torso shape.
#
# Joint ordering (SMPL 24-joint):
#   0=pelvis, 1=left_hip, 2=right_hip, 3=spine1,
#   4=left_knee, 5=right_knee, 6=spine2,
#   7=left_ankle, 8=right_ankle, 9=spine3,
#   ...
#   16=left_shoulder, 17=right_shoulder,
#   18=left_elbow, 19=right_elbow,
#   20=left_wrist, 21=right_wrist,
#
# Pose vector: joint_i has axis-angle at indices [i*3, i*3+1, i*3+2].
# ---------------------------------------------------------------------------
CANONICAL_APOSE = np.zeros(72, dtype=np.float32)
CANONICAL_APOSE[50] = -0.52   # left shoulder Z  → arm down ~30°
CANONICAL_APOSE[53] = +0.52   # right shoulder Z → arm down ~30°
CANONICAL_APOSE[5]  = +0.17   # left hip Z       → leg apart ~10°
CANONICAL_APOSE[8]  = -0.17   # right hip Z      → leg apart ~10°

# SMPL model path (relative to this file)
_SMPL_MODEL_DIR = (
    Path(__file__).resolve().parent
    / "PARE" / "scripts" / "data" / "body_models" / "smpl"
)

# T-pose shape penalty: downweight T-pose betas since PARE's shape
# regression is less reliable when the torso is distorted by T-pose.
TPOSE_SHAPE_PENALTY = 0.5


def fuse_betas(
    all_betas: Dict[str, np.ndarray],
    quality_scores: Dict[str, float],
) -> np.ndarray:
    """Weighted average of per-view SMPL shape betas.

    Parameters
    ----------
    all_betas : dict
        Mapping view_name → shape betas array (10,).
    quality_scores : dict
        Mapping view_name → quality score in [0, 1].

    Returns
    -------
    consensus_betas : np.ndarray of shape (10,)
    """
    views = []
    weights = []
    for view_name, betas in all_betas.items():
        q = quality_scores.get(view_name, 0.0)
        if q <= 0.0:
            continue
        if view_name == "front_t":
            q *= TPOSE_SHAPE_PENALTY
        views.append(np.asarray(betas, dtype=np.float64))
        weights.append(q)

    if not views:
        raise RuntimeError("No valid views for beta fusion")

    views = np.stack(views)            # (N, 10)
    weights = np.array(weights)        # (N,)
    weights /= weights.sum()           # normalize

    consensus = np.average(views, axis=0, weights=weights)  # (10,)
    return consensus.astype(np.float32)


def build_consensus_mesh(
    consensus_betas: np.ndarray,
    device_str: str = "cpu",
) -> Tuple[np.ndarray, np.ndarray]:
    """Build a single SMPL mesh from consensus betas in canonical A-pose.

    Parameters
    ----------
    consensus_betas : (10,) array
    device_str : "cuda" or "cpu"

    Returns
    -------
    vertices : (6890, 3) float32 ndarray  — mesh in metres
    joints   : (45, 3)   float32 ndarray  — regressed joints in metres
    """
    import torch
    from smplx import SMPL

    device = torch.device(device_str)

    smpl = SMPL(
        model_path=str(_SMPL_MODEL_DIR),
        gender="neutral",
        batch_size=1,
    ).to(device)

    betas_t = torch.tensor(consensus_betas, dtype=torch.float32).unsqueeze(0).to(device)
    pose_t = torch.tensor(CANONICAL_APOSE, dtype=torch.float32).unsqueeze(0).to(device)

    with torch.no_grad():
        output = smpl(
            betas=betas_t,
            body_pose=pose_t[:, 3:],
            global_orient=pose_t[:, :3],
        )

    vertices = output.vertices[0].cpu().numpy()   # (6890, 3)
    joints = output.joints[0].cpu().numpy()        # (45, 3)

    del betas_t, pose_t, output, smpl
    if device_str == "cuda":
        torch.cuda.empty_cache()

    logger.info(
        "Consensus mesh built: %d verts, height=%.4f m",
        vertices.shape[0],
        vertices[:, 1].max() - vertices[:, 1].min(),
    )
    return vertices, joints


# ---------------------------------------------------------------------------
# SMPL 24-joint name → index map (used by measurement code)
# ---------------------------------------------------------------------------
SMPL_JOINT_MAP = {
    "pelvis": 0,
    "left_hip": 1,    "right_hip": 2,
    "spine1": 3,
    "left_knee": 4,   "right_knee": 5,
    "spine2": 6,
    "left_ankle": 7,  "right_ankle": 8,
    "spine3": 9,
    "left_foot": 10,  "right_foot": 11,
    "neck": 12,
    "left_collar": 13, "right_collar": 14,
    "head": 15,
    "left_shoulder": 16, "right_shoulder": 17,
    "left_elbow": 18,    "right_elbow": 19,
    "left_wrist": 20,    "right_wrist": 21,
    "left_hand": 22,     "right_hand": 23,
}
