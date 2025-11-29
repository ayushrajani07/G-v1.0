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
import concurrent.futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .interfaces import PathForecaster
from .config_structs import EnsembleConfig
from .components import (
    BaselineComponent,
    GBRTComponent,
    ResidualComponent,
    RetrievalComponent,
    ConformalComponent
)
from .params import (
    sanitize_horizon as _p_horizon,
    sanitize_bucket_ms as _p_bucket,
)

_LOG = logging.getLogger("path_forecast.ensemble")


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
        self._baseline = BaselineComponent(
            enabled=self.cfg.baseline_enabled,
            k=self.cfg.baseline_k
        )
        
        # Phase 18: Support pluggable residual models (GBRT or LSTM)
        # Phase 19: Hybrid Ensemble - Initialize both if needed, or switch based on config
        # For now, we initialize GBRT as primary, but we can add LSTM as secondary
        
        self._gbrt = GBRTComponent(
            enabled=self.cfg.gbrt_enabled,
            model_path=self.cfg.gbrt_model_path,
            feature_config=self.cfg.gbrt_feature_config
        )
        
        # Optional LSTM component (can be enabled via config in future)
        # self._lstm = ResidualComponent(enabled=..., model_path=..., model_type="lstm")
        
        # Phase 19: Meta-Learner (placeholder for now, to be integrated)
        # self._meta_learner = EnsembleWeightLearner(components=["baseline", "gbrt", "retrieval"])
        
        self._retrieval = RetrievalComponent(
            enabled=self.cfg.retrieval_enabled,
            config=self.cfg
        )
        
        self._conformal = ConformalComponent(
            enabled=self.cfg.conformal_enabled,
            target_coverage=self.cfg.conformal_target_coverage,
            window=self.cfg.conformal_window,
            min_radius=self.cfg.conformal_min_radius
        )
            
        # Phase 16: Persistent ThreadPool
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="EnsembleWorker")
    
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
            baseline_value = self._baseline.compute(underlying, avg_iv, minutes_to_expiry)
            self.last_meta["baseline_tp"] = baseline_value
            
            # Step 2 & 3: Parallel execution of GBRT and Retrieval
            # Phase 14: Speculative Execution
            # Phase 16: Use persistent executor
            # Phase 17.3: Granular Error Handling
            future_gbrt = self._executor.submit(
                self._gbrt.forecast_residuals, recent_window, context, qlist, H, self._baseline
            )
            future_retrieval = self._executor.submit(
                self._retrieval.forecast, recent_window, context, qlist, H, _bucket
            )
            
            # Handle component failures gracefully
            # Initialize with safe defaults
            gbrt_residuals = {q: [0.0] * H for q in qlist}
            # Retrieval default should be baseline (0 residual)
            retrieval_forecast = {q: [baseline_value] * H for q in qlist}
            
            try:
                gbrt_residuals = future_gbrt.result()
                self.last_meta["gbrt_status"] = "ok"
                self.last_meta["gbrt_available"] = True
            except Exception as e:
                _LOG.warning(f"GBRT component failed: {e}")
                self.last_meta["gbrt_status"] = "failed"
                self.last_meta["gbrt_error"] = str(e)
                self.last_meta["gbrt_available"] = False
                
            try:
                retrieval_forecast, retr_meta = future_retrieval.result()
                self.last_meta["retrieval_status"] = "ok"
                self.last_meta["retrieval_available"] = True
                self.last_meta["retrieval_candidates"] = retr_meta.get("candidates_total", 0)
                self.last_meta["retrieval_k"] = retr_meta.get("k_used", self.cfg.retrieval_k)
            except Exception as e:
                _LOG.warning(f"Retrieval component failed: {e}")
                self.last_meta["retrieval_status"] = "failed"
                self.last_meta["retrieval_error"] = str(e)
                self.last_meta["retrieval_available"] = False
            
            # Step 4: Compute confidence and adaptive weights
            confidence = self._compute_confidence(context)
            weights = self._compute_weights(confidence, context)
            
            # Adjust weights based on component health
            if self.last_meta.get("gbrt_status") == "failed":
                weights["gbrt"] = 0.0
                weights["retrieval"] = 1.0
            if self.last_meta.get("retrieval_status") == "failed":
                weights["retrieval"] = 0.0
                weights["gbrt"] = 1.0
            
            # If both failed, weights will be effectively ignored as residuals are 0
            # but we should probably flag it
            if weights["gbrt"] == 0.0 and weights["retrieval"] == 0.0:
                self.last_meta["fallback_active"] = True
            
            self.last_meta["confidence"] = confidence
            self.last_meta["weight_gbrt"] = weights["gbrt"]
            self.last_meta["weight_retrieval"] = weights["retrieval"]
            
            # Step 5: Combine forecasts
            combined_forecast = self._combine_forecasts(
                baseline_value, gbrt_residuals, retrieval_forecast, 
                weights, qlist, H
            )
            
            # Step 6: Apply conformal calibration
            final_forecast = self._conformal.apply(combined_forecast, qlist, H)
            
            # Record timing
            if self.cfg.enable_profiling:
                self.last_meta['total_ms'] = int((time.perf_counter() - t_start) * 1000)
            
            return times, final_forecast
            
        except Exception as e:
            _LOG.error(f"Ensemble forecast failed: {e}", exc_info=True)
            self.last_meta["error"] = str(e)
            # Return fallback flat forecast
            return self._fallback_forecast(recent_window, context, qlist, H, times)
    
    
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
    
    def _compute_weights(self, confidence: float, context: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
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
        
        # If retrieval failed, we treat its residual as 0.0 (baseline fallback)
        # If GBRT failed, we treat its residual as 0.0 (baseline fallback)
        
        for q in quantiles:
            gbrt_res = gbrt_residuals.get(q, [0.0] * horizon)
            retr_vals = retrieval_forecast.get(q, [baseline] * horizon)
            
            combined_q = []
            for i in range(horizon):
                # Extract retrieval residual (retrieval forecast - baseline)
                # If retrieval failed, retr_vals will be [0.0]*H (from init) or empty
                # We need to be careful: if retrieval failed, we want residual to be 0
                # But if retrieval returned 0.0 (failure fallback), then 0.0 - baseline = -baseline
                # This is wrong. We should check status.
                
                retr_val = retr_vals[i] if i < len(retr_vals) else baseline
                
                # If retrieval failed, retr_val is baseline (from initialization)
                # In that case, residual should be 0.0
                if self.last_meta.get("retrieval_status") == "failed":
                    retr_res = 0.0
                else:
                    retr_res = retr_val - baseline
                
                gbrt_res_i = gbrt_res[i] if i < len(gbrt_res) else 0.0
                
                # Weighted combination of residuals
                blended_residual = w_gbrt * gbrt_res_i + w_retrieval * retr_res
                
                # Add back baseline
                combined_tp = baseline + blended_residual
                combined_q.append(float(combined_tp))
            
            combined[q] = combined_q
        
        return combined
    
    
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
            last_tp = self._baseline.compute(underlying, avg_iv, minutes_to_expiry)
        
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
        self._conformal.update(predicted, actual)

    def adapt_conformal_coverage(self, current_norm_error: float) -> float:
        """Adapt conformal target coverage based on normalized error.
        
        Args:
            current_norm_error: Recent normalized error metric
            
        Returns:
            New target coverage
        """
        return self._conformal.adapt_coverage(current_norm_error)
