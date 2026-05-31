"""
Learned correction model for body measurements.

Trains a simple per-key linear regression from raw SMPL-derived measurements
+ user metadata (BMI, height, gender, body_model) to corrected measurements.
Falls back to identity (no correction) when no trained model is available.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(__file__).resolve().parent / "data" / "correction_models"

# Keys the model can correct
CORRECTABLE_KEYS = [
    "chest_circum_cm",
    "waist_circum_cm",
    "hip_circum_cm",
    "neck_circum_cm",
    "upperarm_circum_cm",
    "thigh_circum_cm",
    "calf_circum_cm",
    "sleeve_len_cm",
    "pants_outseam_cm",
    "shoulder_width_cm",
]

# Feature names extracted from measurements dict
FEATURE_KEYS = [
    "user_height_cm",
    "bmi",
    "width_scale",
]


class LinearCorrectionModel:
    """Per-key linear correction: corrected = slope * raw + intercept + features @ weights."""

    def __init__(self):
        # key → {"slope": float, "intercept": float, "feature_weights": list[float]}
        self.params: Dict[str, dict] = {}
        self._loaded = False

    def load(self, path: Optional[str] = None) -> bool:
        """Load trained parameters from JSON.

        File format::

            {
                "chest_circum_cm": {
                    "slope": 0.98,
                    "intercept": 1.5,
                    "feature_weights": [0.01, -0.02, 0.5]
                },
                ...
            }

        Returns True if loaded successfully.
        """
        fpath = Path(path or (_MODEL_DIR / "linear_correction.json"))
        if not fpath.exists():
            self._loaded = False
            return False

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                self.params = json.load(f)
            self._loaded = True
            logger.info(f"Loaded correction model from {fpath}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load correction model: {e}")
            self._loaded = False
            return False

    def save(self, path: Optional[str] = None) -> None:
        """Save trained parameters to JSON."""
        fpath = Path(path or (_MODEL_DIR / "linear_correction.json"))
        fpath.parent.mkdir(parents=True, exist_ok=True)

        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(self.params, f, indent=2)
        logger.info(f"Saved correction model to {fpath}")

    def _extract_features(self, measurements: dict) -> np.ndarray:
        """Extract feature vector from measurements dict."""
        feats = []
        for fk in FEATURE_KEYS:
            val = measurements.get(fk, 0.0)
            if not isinstance(val, (int, float)) or not np.isfinite(val):
                val = 0.0
            feats.append(float(val))
        # Add gender as numeric
        gender = str(measurements.get("gender", "")).lower()
        feats.append(1.0 if gender == "male" else 0.0)
        # Add body_model as numeric
        bm = str(measurements.get("body_model", "adult")).lower()
        bm_map = {"child": 0.0, "teen": 0.5, "adult": 1.0}
        feats.append(bm_map.get(bm, 1.0))
        return np.array(feats, dtype=np.float64)

    def predict(self, measurements: dict) -> dict:
        """Apply learned corrections to measurements.

        If no model is loaded, returns measurements unchanged.
        Only modifies keys present in the trained model.
        """
        if not self._loaded or not self.params:
            return measurements

        features = self._extract_features(measurements)

        for key, p in self.params.items():
            raw = measurements.get(key)
            if raw is None or not isinstance(raw, (int, float)):
                continue
            if not np.isfinite(raw):
                continue

            slope = p.get("slope", 1.0)
            intercept = p.get("intercept", 0.0)
            fw = np.array(p.get("feature_weights", []), dtype=np.float64)

            corrected = slope * float(raw) + intercept
            # Add feature contribution (if weights match feature count)
            if fw.shape[0] == features.shape[0]:
                corrected += float(fw @ features)

            measurements[key] = float(corrected)

        return measurements

    def train(
        self,
        samples: List[dict],
        ground_truths: List[dict],
    ) -> None:
        """Train per-key linear regression from paired data.

        Parameters
        ----------
        samples : list of dict
            Raw measurement dicts (output of measure_consensus).
        ground_truths : list of dict
            Corresponding ground truth measurement dicts.
        """
        for key in CORRECTABLE_KEYS:
            X_list = []
            y_list = []

            for sample, gt in zip(samples, ground_truths):
                raw_val = sample.get(key)
                gt_val = gt.get(key)
                if (raw_val is None or gt_val is None or
                        not isinstance(raw_val, (int, float)) or
                        not isinstance(gt_val, (int, float))):
                    continue
                if not (np.isfinite(raw_val) and np.isfinite(gt_val)):
                    continue

                features = self._extract_features(sample)
                # Feature vector: [raw_value, user_features...]
                x = np.concatenate([[float(raw_val)], features])
                X_list.append(x)
                y_list.append(float(gt_val))

            if len(X_list) < 3:
                logger.info(f"Skipping {key}: only {len(X_list)} samples")
                continue

            X = np.array(X_list)
            y = np.array(y_list)

            # Solve via least squares: y = X @ w + b
            # Add bias column
            X_b = np.column_stack([X, np.ones(len(X))])
            try:
                w, _, _, _ = np.linalg.lstsq(X_b, y, rcond=None)
            except np.linalg.LinAlgError:
                logger.warning(f"lstsq failed for {key}")
                continue

            self.params[key] = {
                "slope": float(w[0]),
                "intercept": float(w[-1]),
                "feature_weights": w[1:-1].tolist(),
            }
            logger.info(
                f"Trained {key}: slope={w[0]:.4f}, intercept={w[-1]:.2f}, "
                f"n_samples={len(X_list)}"
            )

        self._loaded = bool(self.params)


# Module-level singleton
_model: Optional[LinearCorrectionModel] = None


def get_correction_model() -> LinearCorrectionModel:
    """Get or create the singleton correction model."""
    global _model
    if _model is None:
        _model = LinearCorrectionModel()
        _model.load()
    return _model


def apply_learned_correction(measurements: dict) -> dict:
    """Convenience function: apply learned correction if model exists."""
    model = get_correction_model()
    return model.predict(measurements)
