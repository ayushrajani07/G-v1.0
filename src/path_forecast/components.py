from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple
from pathlib import Path
import pandas as pd

from .config_structs import EnsembleConfig, RetrievalConfig
from .retrieval import RetrievalPathForecaster
from ..analytics.ml.baseline import baseline_tp
from ..analytics.ml.quantile import QuantileRegressor
from ..analytics.ml.lstm_model import LSTMQuantileRegressor
from ..analytics.ml.conformal import ConformalBand
from ..analytics.ml.feature_engineering import FeatureEngineer

_LOG = logging.getLogger("path_forecast.components")

class BaselineComponent:
    """Component for calculating structural baseline TP."""
    
    def __init__(self, enabled: bool, k: float = 1.0):
        self.enabled = enabled
        self.k = k

    def compute(self, underlying: float, avg_iv: float, minutes_to_expiry: float) -> float:
        if not self.enabled:
            return 0.0
        try:
            return float(baseline_tp(
                underlying=underlying,
                iv_proxy=avg_iv,
                minutes_to_expiry=minutes_to_expiry,
                k=self.k,
            ))
        except Exception as e:
            _LOG.warning(f"Baseline computation failed: {e}")
            return 0.0

class ResidualComponent:
    """Base component for residual forecasting (GBRT or LSTM)."""
    
    def __init__(self, enabled: bool, model_path: Optional[Path], model_type: str = "gbrt"):
        self.enabled = enabled
        self.model_path = model_path
        self.model_type = model_type
        self._model: Any = None
        self._feature_engineer: Optional[FeatureEngineer] = None
        
        if self.enabled and self.model_path:
            self._load_model()

    def _load_model(self) -> None:
        try:
            if self.model_path and self.model_path.exists():
                if self.model_type == "lstm":
                    self._model = LSTMQuantileRegressor.load(str(self.model_path))
                else:
                    self._model = QuantileRegressor.load(str(self.model_path))
                
                self._feature_engineer = FeatureEngineer()
                _LOG.info(f"Loaded {self.model_type.upper()} model from {self.model_path}")
            else:
                _LOG.warning(f"{self.model_type.upper()} model path not found: {self.model_path}")
        except Exception as e:
            _LOG.error(f"Failed to load {self.model_type.upper()} model: {e}", exc_info=True)
            self._model = None

    def forecast_residuals(
        self,
        recent_window: Sequence[Sequence[float]],
        context: Dict[str, Any],
        quantiles: List[float],
        horizon: int,
        baseline_component: BaselineComponent
    ) -> Dict[float, List[float]]:
        if not self.enabled or self._model is None or self._feature_engineer is None:
            return {q: [0.0] * horizon for q in quantiles}
        
        try:
            # 1. Prepare Data
            if not recent_window:
                return {q: [0.0] * horizon for q in quantiles}
            
            tps = [row[0] for row in recent_window]
            df = pd.DataFrame({'tp_actual': tps})
            
            underlying = float(context.get('underlying', 0.0))
            avg_iv = float(context.get('avg_iv', 0.0))
            minutes_to_expiry = float(context.get('minutes_to_expiry', 375.0))
            
            current_baseline = baseline_component.compute(underlying, avg_iv, minutes_to_expiry)
            
            df['tp_baseline'] = current_baseline
            df['underlying'] = underlying
            df['avg_iv'] = avg_iv
            df['minutes_to_expiry'] = minutes_to_expiry
            
            # 2. Extract Features
            features_df = self._feature_engineer.extract_features(
                df,
                tp_col='tp_actual',
                tp_baseline_col='tp_baseline',
                index_price_col='underlying',
                iv_col='avg_iv',
                minutes_to_expiry_col='minutes_to_expiry'
            )
            
            if len(features_df) == 0:
                 return {q: [0.0] * horizon for q in quantiles}
            
            # Get features for the last row (current time)
            # For LSTM, we might need a sequence, but for now assuming 1-step prediction or similar feature set
            # If LSTM needs sequence, we need to handle that here.
            # Assuming LSTM model handles 2D input (batch, features) by unsqueezing internally if needed
            # or we pass the last N rows if it's a sequence model.
            
            # Current implementation of LSTMQuantileRegressor.predict takes 2D array
            
            last_row = features_df.iloc[[-1]].copy()
            
            # Get expected feature names and ensure they exist
            feature_cols = self._feature_engineer.get_feature_names()
            for col in feature_cols:
                if col not in last_row.columns:
                    last_row[col] = 0.0
            
            # Fill NaNs (e.g. from lags at start of window) with 0
            X = last_row[feature_cols].fillna(0.0).values
            
            # 3. Predict
            # Returns dict: {'q0.10': array([val]), ...}
            predictions = self._model.predict(X)
            
            # 4. Construct Forecast Path
            residuals_map = {}
            for q in quantiles:
                # Match quantile key format
                q_key = f"q{q:.2f}".replace("-0", "0")
                
                pred_val = 0.0
                if q_key in predictions:
                    pred_val = float(predictions[q_key][0])
                
                # Linearly interpolate residual from 0 to pred_val over horizon
                residuals = []
                for t in range(1, horizon + 1):
                    res_t = (t / horizon) * pred_val
                    residuals.append(res_t)
                
                residuals_map[q] = residuals
            
            return residuals_map
            
        except Exception as e:
            _LOG.warning(f"{self.model_type.upper()} forecast failed: {e}", exc_info=True)
            return {q: [0.0] * horizon for q in quantiles}

class GBRTComponent(ResidualComponent):
    """Legacy wrapper for GBRT component."""
    def __init__(self, enabled: bool, model_path: Optional[Path], feature_config: Optional[Dict[str, Any]] = None):
        super().__init__(enabled, model_path, model_type="gbrt")

class RetrievalComponent:
    """Component for retrieval-based forecasting."""
    
    def __init__(self, enabled: bool, config: EnsembleConfig):
        self.enabled = enabled
        self._forecaster: Optional[RetrievalPathForecaster] = None
        
        if self.enabled and config.retrieval_root:
            self._init_forecaster(config)

    def _init_forecaster(self, cfg: EnsembleConfig) -> None:
        try:
            retrieval_cfg = RetrievalConfig(
                root=cfg.retrieval_root,
                expiry_tag=cfg.retrieval_expiry_tag,
                offset=cfg.retrieval_offset,
                window=cfg.retrieval_window,
                k=cfg.retrieval_k,
                min_days=cfg.retrieval_min_days,
                distance_metric=cfg.retrieval_distance_metric,
                weight_mode=cfg.retrieval_weight_mode,
                use_ann=cfg.retrieval_use_ann,
            )
            self._forecaster = RetrievalPathForecaster(retrieval_cfg)
            _LOG.info("Initialized retrieval forecaster")
        except Exception as e:
            _LOG.error(f"Failed to initialize retrieval: {e}", exc_info=True)
            self._forecaster = None

    def forecast(
        self,
        recent_window: Sequence[Sequence[float]],
        context: Dict[str, Any],
        quantiles: List[float],
        horizon: int,
        bucket_ms: int,
    ) -> Tuple[Dict[float, List[float]], Dict[str, Any]]:
        if not self.enabled or self._forecaster is None:
            return {q: [0.0] * horizon for q in quantiles}, {}
        
        try:
            _, retrieval_qmap = self._forecaster.forecast_path(
                recent_window,
                context=context,
                quantiles=quantiles,
                horizon_minutes=horizon,
                bucket_ms=bucket_ms,
            )
            
            meta = {}
            if hasattr(self._forecaster, 'last_meta'):
                meta = self._forecaster.last_meta or {}
            
            retrieval_forecast = {}
            for q in quantiles:
                retrieval_forecast[q] = list(retrieval_qmap.get(q, [0.0] * horizon))
            
            return retrieval_forecast, meta
            
        except Exception as e:
            raise e

class ConformalComponent:
    """Component for conformal calibration."""
    
    def __init__(self, enabled: bool, target_coverage: float, window: int, min_radius: float):
        self.enabled = enabled
        self._band: Optional[ConformalBand] = None
        
        if self.enabled:
            self._band = ConformalBand(
                target_coverage=target_coverage,
                window=window,
                min_radius=min_radius,
            )

    def apply(
        self,
        forecast: Dict[float, List[float]],
        quantiles: List[float],
        horizon: int,
    ) -> Dict[float, Sequence[float]]:
        if not self.enabled or self._band is None:
            return {q: tuple(forecast.get(q, [0.0] * horizon)) for q in quantiles}
        
        # Placeholder for full implementation
        calibrated = {}
        for q in quantiles:
            calibrated[q] = tuple(forecast.get(q, [0.0] * horizon))
        
        return calibrated

    def update(self, predicted: float, actual: float) -> None:
        if self._band is not None:
            self._band.update(predicted, actual)

    def adapt_coverage(self, current_norm_error: float) -> float:
        if self._band is not None:
            return self._band.adapt_target_coverage(current_norm_error, target_norm_error=0.1)
        return 0.8
