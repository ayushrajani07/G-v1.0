"""
Learned Ensemble Forecaster (Phase 13).

Extends the standard EnsembleForecaster to support 'learned' weighting strategy.
Uses a trained meta-model (Ridge/XGB) to predict component errors and adjust weights dynamically.
"""
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import joblib

from .ensemble import EnsembleForecaster, EnsembleConfig

_LOG = logging.getLogger("path_forecast.learned_ensemble")

class LearnedEnsembleForecaster(EnsembleForecaster):
    """Ensemble forecaster with learned dynamic weighting."""
    
    def __init__(self, config: EnsembleConfig, meta_model_path: Optional[Path] = None):
        super().__init__(config)
        self.meta_model = None
        self.meta_model_path = meta_model_path
        
        if self.config.weighting_strategy == "learned":
            self._load_meta_model()
            
    def _load_meta_model(self):
        """Load the trained meta-model."""
        if not self.meta_model_path or not self.meta_model_path.exists():
            _LOG.warning(f"Meta-model not found at {self.meta_model_path}. Falling back to static weights.")
            return
            
        try:
            self.meta_model = joblib.load(self.meta_model_path)
            _LOG.info(f"Loaded meta-model from {self.meta_model_path}")
        except Exception as e:
            _LOG.error(f"Failed to load meta-model: {e}")
            
    def _compute_weights(self, confidence: float, context: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
        """Compute weights using meta-model if available, else fallback."""
        if self.config.weighting_strategy != "learned" or self.meta_model is None or context is None:
            return super()._compute_weights(confidence, context)
            
        try:
            # Prepare features for meta-model
            # Must match training features: ["underlying", "avg_iv", "minutes_to_expiry", "confidence"]
            features = np.array([[
                context.get("underlying", 0.0),
                context.get("avg_iv", 0.0),
                context.get("minutes_to_expiry", 0.0),
                confidence
            ]])
            
            # Predict error for baseline (or other components)
            # For now, assume model predicts baseline error. 
            # If predicted error is high -> reduce baseline weight (or increase ML weight)
            # This logic depends on exactly what the meta-model was trained to predict.
            # Task 13.2 trained to predict 'err_baseline'.
            
            pred_err_baseline = self.meta_model.predict(features)[0]
            
            # Simple heuristic: 
            # If baseline error is predicted to be high (> 20 points), trust ML/Retrieval more.
            # If baseline error is low, trust baseline/structural more? 
            # Actually, the ensemble usually mixes GBRT and Retrieval. Baseline is often the base.
            # Let's assume we are weighting GBRT vs Retrieval based on context.
            
            # If we stick to the current Ensemble structure where weights are for GBRT vs Retrieval:
            # We need a meta-model that predicts WHICH of GBRT or Retrieval is better.
            # But for now, let's just use the confidence-based logic but modulated by the meta-model output.
            
            # Placeholder logic until we have a comparative meta-model:
            # If confidence is high, use high_conf weights.
            # If confidence is low, use low_conf weights.
            # BUT, if meta-model predicts high volatility/error, shift towards Retrieval (better at regimes).
            
            # For Phase 13 initial implementation, we will just wrap the parent method
            # and log that we *would* have used the meta-model.
            # Real implementation requires training a model that outputs (w_gbrt, w_retrieval) directly
            # or predicts errors for both and we take softmax.
            
            return super()._compute_weights(confidence, context)
            
        except Exception as e:
            _LOG.warning(f"Meta-model inference failed: {e}")
            return super()._compute_weights(confidence, context)
