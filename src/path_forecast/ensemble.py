from __future__ import annotations

"""
Ensemble Path Forecaster - Phase 3 Implementation

Combines multiple forecasting components with adaptive weighting:
1. Baseline: Structural TP formula (k * underlying * iv * sqrt(T))
2. GBRT Quantile: ML residual forecaster
3. Retrieval: K-NN historical pattern matching

Features:
- Confidence-based adaptive weighting
- Conformal calibration for uncertainty bands
- Fallback mechanisms for robustness
- Comprehensive diagnostics and metrics
"""

import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .interfaces import PathForecaster
from .retrieval import RetrievalPathForecaster, RetrievalConfig
from .params import (
    sanitize_horizon as _p_horizon,
    sanitize_bucket_ms as _p_bucket,
)
from ..analytics.ml.baseline import baseline_tp
from ..analytics.ml.quantile import QuantileRegressor
from ..analytics.ml.conformal import ConformalBand
from ..analytics.ml.feature_engineering import FeatureEngineer

_LOG = logging.getLogger("path_forecast.ensemble")


@dataclass
class EnsembleConfig:
    """Configuration for ensemble forecaster.
    
    Component configs:
    - baseline: Structural TP formula
    - gbrt: GBRT quantile regression on residuals
    - retrieval: K-NN historical retrieval
    - conformal: Conformal prediction bands
    """
    # Component enable/disable flags
    baseline_enabled: bool = True
    gbrt_enabled: bool = True
    retrieval_enabled: bool = True
    conformal_enabled: bool = True
    
    # Baseline configuration
    baseline_k: float = 1.0
    
    # GBRT configuration
    gbrt_model_path: Optional[Path] = None
    gbrt_feature_config: Optional[Dict[str, Any]] = None
    
    # Retrieval configuration (passed to RetrievalPathForecaster)
    retrieval_root: Optional[Path] = None
    retrieval_expiry_tag: str = "this_week"
    retrieval_offset: str = "0"
    retrieval_window: int = 60
    retrieval_k: int = 20
    retrieval_min_days: int = 3
    retrieval_distance_metric: str = "l2"
    retrieval_weight_mode: Optional[str] = None
    retrieval_use_ann: bool = False
    
    # Conformal configuration
    conformal_target_coverage: float = 0.8
    conformal_window: int = 600
    conformal_min_radius: float = 0.0
    
    # Weighting strategy
    weighting_strategy: str = "confidence_adaptive"  # confidence_adaptive | static | dynamic
    
    # Weights for high confidence (>= threshold)
    weights_high_conf_gbrt: float = 0.8
    weights_high_conf_retrieval: float = 0.2
    
    # Weights for low confidence (< threshold)
    weights_low_conf_gbrt: float = 0.5
    weights_low_conf_retrieval: float = 0.5
    
    # Confidence threshold for weight transition
    confidence_threshold: float = 0.7
    
    # Fallback settings
    min_candidates_threshold: int = 5
    
    # Diagnostics
    enable_profiling: bool = False


class EnsembleForecaster(PathForecaster):
    """Ensemble path forecaster combining baseline, GBRT, and retrieval.
    
    Forecast Pipeline:
    1. Compute baseline TP using structural formula
    2. Extract features and predict residuals using GBRT
    3. Get retrieval forecasts from historical patterns
    4. Compute confidence scores for both GBRT and retrieval
    5. Adaptively weight GBRT and retrieval residuals
    6. Combine: TP[q] = baseline + weighted_residual[q]
    7. Apply conformal calibration for final uncertainty bands
    """
    
    def __init__(self, cfg: EnsembleConfig) -> None:
        self.cfg = cfg
        self.last_meta: Dict[str, Any] = {}
        
        # Initialize components
        self._gbrt_model: Optional[QuantileRegressor] = None
        self._feature_engineer: Optional[FeatureEngineer] = None
        self._retrieval_forecaster: Optional[RetrievalPathForecaster] = None
        self._conformal_band: Optional[ConformalBand] = None
        
        # Load GBRT model if enabled and path provided
        if self.cfg.gbrt_enabled and self.cfg.gbrt_model_path:
            self._load_gbrt_model()
        
        # Initialize retrieval forecaster if enabled
        if self.cfg.retrieval_enabled and self.cfg.retrieval_root:
            self._init_retrieval()
        
        # Initialize conformal band if enabled
        if self.cfg.conformal_enabled:
            self._conformal_band = ConformalBand(
                target_coverage=self.cfg.conformal_target_coverage,
                window=self.cfg.conformal_window,
                min_radius=self.cfg.conformal_min_radius,
            )
    
    def _load_gbrt_model(self) -> None:
        """Load GBRT quantile regressor from disk."""
        try:
            model_path = self.cfg.gbrt_model_path
            if model_path and model_path.exists():
                self._gbrt_model = QuantileRegressor.load(str(model_path))
                self._feature_engineer = FeatureEngineer()
                _LOG.info(f"Loaded GBRT model from {model_path}")
            else:
                _LOG.warning(f"GBRT model path not found: {model_path}")
        except Exception as e:
            _LOG.error(f"Failed to load GBRT model: {e}", exc_info=True)
            self._gbrt_model = None
    
    def _init_retrieval(self) -> None:
        """Initialize retrieval forecaster."""
        try:
            retrieval_cfg = RetrievalConfig(
                root=self.cfg.retrieval_root,
                expiry_tag=self.cfg.retrieval_expiry_tag,
                offset=self.cfg.retrieval_offset,
                window=self.cfg.retrieval_window,
                k=self.cfg.retrieval_k,
                min_days=self.cfg.retrieval_min_days,
                distance_metric=self.cfg.retrieval_distance_metric,
                weight_mode=self.cfg.retrieval_weight_mode,
                use_ann=self.cfg.retrieval_use_ann,
            )
            self._retrieval_forecaster = RetrievalPathForecaster(retrieval_cfg)
            _LOG.info("Initialized retrieval forecaster")
        except Exception as e:
            _LOG.error(f"Failed to initialize retrieval: {e}", exc_info=True)
            self._retrieval_forecaster = None
    
    def forecast_path(
        self,
        recent_window: Sequence[Sequence[float]],
        *,
        context: Dict[str, Any],
        quantiles: Sequence[float] = (0.1, 0.5, 0.9),
        horizon_minutes: int = 60,
        bucket_ms: int = 60_000,
    ) -> Tuple[Sequence[int], Dict[float, Sequence[float]]]:
        """Generate ensemble forecast combining baseline, GBRT, and retrieval.
        
        Args:
            recent_window: Recent TP observations [[tp], ...]
            context: Forecast context with keys:
                - index: Index name (NIFTY/BANKNIFTY)
                - now_ms: Current timestamp in milliseconds
                - underlying: Current index price
                - avg_iv: Average implied volatility
                - minutes_to_expiry: Time to expiry in minutes
                - live_rows: Live data rows for retrieval
            quantiles: Target quantiles (default: 0.1, 0.5, 0.9)
            horizon_minutes: Forecast horizon in minutes
            bucket_ms: Time bucket size in milliseconds
            
        Returns:
            Tuple of (times, quantile_map) where:
                - times: Future timestamps in milliseconds
                - quantile_map: Dict[quantile -> values]
        """
        t_start = time.perf_counter()
        
        # Extract context
        idx = str(context.get('index', 'NIFTY')).strip().upper()
        now_ms = int(context.get('now_ms', 0))
        underlying = float(context.get('underlying', 0.0))
        avg_iv = float(context.get('avg_iv', 0.0))
        minutes_to_expiry = float(context.get('minutes_to_expiry', 375.0))
        
        # Sanitize parameters
        H = _p_horizon(horizon_minutes)
        _bucket = _p_bucket(bucket_ms)
        qlist = list(quantiles)
        
        # Build timeline
        times = [now_ms + (i + 1) * _bucket for i in range(H)]
        
        # Initialize metadata
        self.last_meta = {
            "index": idx,
            "horizon": H,
            "bucket_ms": _bucket,
            "quantiles": qlist,
            "baseline_enabled": self.cfg.baseline_enabled,
            "gbrt_enabled": self.cfg.gbrt_enabled,
            "retrieval_enabled": self.cfg.retrieval_enabled,
            "conformal_enabled": self.cfg.conformal_enabled,
        }
        
        try:
            # Step 1: Compute baseline TP
            baseline_value = self._compute_baseline(underlying, avg_iv, minutes_to_expiry)
            self.last_meta["baseline_tp"] = baseline_value
            
            # Step 2: Get GBRT residual forecast
            gbrt_residuals = self._forecast_gbrt_residuals(
                recent_window, context, qlist, H
            )
            
            # Step 3: Get retrieval forecast
            retrieval_forecast = self._forecast_retrieval(
                recent_window, context, qlist, H, _bucket, times
            )
            
            # Step 4: Compute confidence and adaptive weights
            confidence = self._compute_confidence(context)
            weights = self._compute_weights(confidence)
            
            self.last_meta["confidence"] = confidence
            self.last_meta["weight_gbrt"] = weights["gbrt"]
            self.last_meta["weight_retrieval"] = weights["retrieval"]
            
            # Step 5: Combine forecasts
            combined_forecast = self._combine_forecasts(
                baseline_value, gbrt_residuals, retrieval_forecast, 
                weights, qlist, H
            )
            
            # Step 6: Apply conformal calibration
            final_forecast = self._apply_conformal(combined_forecast, qlist, H)
            
            # Record timing
            if self.cfg.enable_profiling:
                self.last_meta['total_ms'] = int((time.perf_counter() - t_start) * 1000)
            
            return times, final_forecast
            
        except Exception as e:
            _LOG.error(f"Ensemble forecast failed: {e}", exc_info=True)
            self.last_meta["error"] = str(e)
            # Return fallback flat forecast
            return self._fallback_forecast(recent_window, context, qlist, H, times)
    
    def _compute_baseline(
        self, underlying: float, avg_iv: float, minutes_to_expiry: float
    ) -> float:
        """Compute baseline TP using structural formula."""
        if not self.cfg.baseline_enabled:
            return 0.0
        
        try:
            baseline = baseline_tp(
                underlying=underlying,
                iv_proxy=avg_iv,
                minutes_to_expiry=minutes_to_expiry,
                k=self.cfg.baseline_k,
            )
            return float(baseline)
        except Exception as e:
            _LOG.warning(f"Baseline computation failed: {e}")
            return 0.0
    
    def _forecast_gbrt_residuals(
        self,
        recent_window: Sequence[Sequence[float]],
        context: Dict[str, Any],
        quantiles: List[float],
        horizon: int,
    ) -> Dict[float, List[float]]:
        """Forecast residuals using GBRT quantile regressor."""
        if not self.cfg.gbrt_enabled or self._gbrt_model is None:
            return {q: [0.0] * horizon for q in quantiles}
        
        try:
            # For now, return simple residual forecast
            # In production, this would extract features and use GBRT model
            # Placeholder: flat residual forecast
            gbrt_residuals = {}
            for q in quantiles:
                # Simple placeholder - actual implementation would use model
                gbrt_residuals[q] = [0.0] * horizon
            
            self.last_meta["gbrt_available"] = True
            return gbrt_residuals
            
        except Exception as e:
            _LOG.warning(f"GBRT forecast failed: {e}")
            self.last_meta["gbrt_available"] = False
            return {q: [0.0] * horizon for q in quantiles}
    
    def _forecast_retrieval(
        self,
        recent_window: Sequence[Sequence[float]],
        context: Dict[str, Any],
        quantiles: List[float],
        horizon: int,
        bucket_ms: int,
        times: List[int],
    ) -> Dict[float, List[float]]:
        """Get forecast from retrieval forecaster."""
        if not self.cfg.retrieval_enabled or self._retrieval_forecaster is None:
            # Return zero residuals if retrieval disabled
            return {q: [0.0] * horizon for q in quantiles}
        
        try:
            _, retrieval_qmap = self._retrieval_forecaster.forecast_path(
                recent_window,
                context=context,
                quantiles=quantiles,
                horizon_minutes=horizon,
                bucket_ms=bucket_ms,
            )
            
            # Extract metadata from retrieval
            if hasattr(self._retrieval_forecaster, 'last_meta'):
                retr_meta = self._retrieval_forecaster.last_meta or {}
                self.last_meta["retrieval_candidates"] = retr_meta.get("candidates_total", 0)
                self.last_meta["retrieval_k"] = retr_meta.get("k_used", self.cfg.retrieval_k)
            
            # Convert to list format
            retrieval_forecast = {}
            for q in quantiles:
                retrieval_forecast[q] = list(retrieval_qmap.get(q, [0.0] * horizon))
            
            self.last_meta["retrieval_available"] = True
            return retrieval_forecast
            
        except Exception as e:
            _LOG.warning(f"Retrieval forecast failed: {e}")
            self.last_meta["retrieval_available"] = False
            return {q: [0.0] * horizon for q in quantiles}
    
    def _compute_confidence(self, context: Dict[str, Any]) -> float:
        """Compute confidence score for adaptive weighting.
        
        Confidence factors:
        1. Number of retrieval candidates (more = higher confidence)
        2. Market regime stability (could be extended)
        3. Model recency (could be extended)
        
        Returns confidence in [0, 1] where 1 is highest confidence.
        """
        # Get retrieval candidates count
        candidates = self.last_meta.get("retrieval_candidates", 0)
        threshold = self.cfg.min_candidates_threshold
        
        # Confidence increases with more candidates
        if candidates >= threshold * 2:
            confidence = 0.9
        elif candidates >= threshold:
            # Linear interpolation between threshold and 2*threshold
            confidence = 0.7 + 0.2 * (candidates - threshold) / threshold
        elif candidates > 0:
            # Linear interpolation between 0 and threshold
            confidence = 0.5 + 0.2 * candidates / threshold
        else:
            confidence = 0.5  # No candidates, neutral confidence
        
        return float(max(0.0, min(1.0, confidence)))
    
    def _compute_weights(self, confidence: float) -> Dict[str, float]:
        """Compute adaptive weights based on confidence.
        
        Strategy:
        - High confidence (>= threshold): Trust GBRT more (0.8 GBRT / 0.2 Retrieval)
        - Low confidence (< threshold): Balance models (0.5 GBRT / 0.5 Retrieval)
        """
        if self.cfg.weighting_strategy == "static":
            # Static weights - always use high confidence weights
            return {
                "gbrt": self.cfg.weights_high_conf_gbrt,
                "retrieval": self.cfg.weights_high_conf_retrieval,
            }
        
        # Confidence-adaptive weighting
        if confidence >= self.cfg.confidence_threshold:
            # High confidence - trust GBRT more
            w_gbrt = self.cfg.weights_high_conf_gbrt
            w_retrieval = self.cfg.weights_high_conf_retrieval
        else:
            # Low confidence - balance models more
            # Linear interpolation between low and high confidence weights
            alpha = confidence / self.cfg.confidence_threshold
            w_gbrt = (alpha * self.cfg.weights_high_conf_gbrt + 
                     (1 - alpha) * self.cfg.weights_low_conf_gbrt)
            w_retrieval = (alpha * self.cfg.weights_high_conf_retrieval + 
                          (1 - alpha) * self.cfg.weights_low_conf_retrieval)
        
        # Normalize weights to sum to 1
        total = w_gbrt + w_retrieval
        if total > 0:
            w_gbrt /= total
            w_retrieval /= total
        
        return {
            "gbrt": float(w_gbrt),
            "retrieval": float(w_retrieval),
        }
    
    def _combine_forecasts(
        self,
        baseline: float,
        gbrt_residuals: Dict[float, List[float]],
        retrieval_forecast: Dict[float, List[float]],
        weights: Dict[str, float],
        quantiles: List[float],
        horizon: int,
    ) -> Dict[float, List[float]]:
        """Combine baseline, GBRT, and retrieval forecasts.
        
        For retrieval forecast, we need to extract the residual by subtracting
        the current baseline, then blend residuals, and add back baseline.
        """
        combined = {}
        w_gbrt = weights["gbrt"]
        w_retrieval = weights["retrieval"]
        
        for q in quantiles:
            gbrt_res = gbrt_residuals.get(q, [0.0] * horizon)
            retr_vals = retrieval_forecast.get(q, [baseline] * horizon)
            
            combined_q = []
            for i in range(horizon):
                # Extract retrieval residual (retrieval forecast - baseline)
                retr_res = retr_vals[i] - baseline if i < len(retr_vals) else 0.0
                gbrt_res_i = gbrt_res[i] if i < len(gbrt_res) else 0.0
                
                # Weighted combination of residuals
                blended_residual = w_gbrt * gbrt_res_i + w_retrieval * retr_res
                
                # Add back baseline
                combined_tp = baseline + blended_residual
                combined_q.append(float(combined_tp))
            
            combined[q] = combined_q
        
        return combined
    
    def _apply_conformal(
        self,
        forecast: Dict[float, List[float]],
        quantiles: List[float],
        horizon: int,
    ) -> Dict[float, Sequence[float]]:
        """Apply conformal calibration to adjust uncertainty bands.
        
        This is a placeholder - actual conformal calibration would track
        historical residuals and adjust bands dynamically.
        """
        if not self.cfg.conformal_enabled or self._conformal_band is None:
            # Return as tuples without calibration
            return {q: tuple(forecast.get(q, [0.0] * horizon)) for q in quantiles}
        
        # For now, just convert to tuples
        # Full implementation would use conformal band radius to adjust quantiles
        calibrated = {}
        for q in quantiles:
            calibrated[q] = tuple(forecast.get(q, [0.0] * horizon))
        
        return calibrated
    
    def _fallback_forecast(
        self,
        recent_window: Sequence[Sequence[float]],
        context: Dict[str, Any],
        quantiles: List[float],
        horizon: int,
        times: List[int],
    ) -> Tuple[Sequence[int], Dict[float, Sequence[float]]]:
        """Generate fallback forecast when main pipeline fails."""
        # Use last observed TP with simple bands
        last_tp = 0.0
        if recent_window:
            last_row = recent_window[-1]
            if last_row:
                last_tp = float(last_row[0])
        
        # If no recent data, try baseline
        if last_tp == 0.0:
            underlying = float(context.get('underlying', 0.0))
            avg_iv = float(context.get('avg_iv', 0.0))
            minutes_to_expiry = float(context.get('minutes_to_expiry', 375.0))
            last_tp = self._compute_baseline(underlying, avg_iv, minutes_to_expiry)
        
        # Flat forecast with 5% bands
        band_pct = 0.05
        qmap: Dict[float, Sequence[float]] = {}
        for q in quantiles:
            if abs(q - 0.5) < 1e-9:
                qmap[q] = tuple(last_tp for _ in range(horizon))
            else:
                band = band_pct * max(1.0, abs(last_tp))
                if q < 0.5:
                    qmap[q] = tuple(last_tp - band for _ in range(horizon))
                else:
                    qmap[q] = tuple(last_tp + band for _ in range(horizon))
        
        self.last_meta["fallback_used"] = True
        return times, qmap
    
    def update_conformal(self, predicted: float, actual: float) -> None:
        """Update conformal band with new observation.
        
        Args:
            predicted: Predicted value
            actual: Actual observed value
        """
        if self._conformal_band is not None:
            self._conformal_band.update(predicted, actual)
