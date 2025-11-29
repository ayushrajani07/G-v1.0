"""Drift attribution breakdown (Phase 11).

Provides decomposition of drift signals into components:
- tail_ratio: short decay-weighted p95 vs long baseline
- trend_ratio: residual short/long trend ratio
- burn_rate: short-long acceleration delta
- weight_divergence: absolute difference of gbrt vs retrieval weights
- regime_class: health classification (1/2/3)
- retrain_signal: smoothed adaptive retrain signal if available (fallback 0)

Usage:
  from src.ml.drift_attribution import compute_drift_components
  components = compute_drift_components(index, horizon)
"""
from __future__ import annotations
from typing import Dict, Any
import time

from src.ml.residuals import get_residual_stats, get_residual_trend
try:
    from src.ml.weight_volatility import get_weight_volatility  # type: ignore
except Exception:  # pragma: no cover
    def get_weight_volatility(index: str, horizon: int, window_seconds: int) -> tuple[float, float]:
        return 0.0, 0.0
try:
    from src.ml.weighting import get_weighting_engine  # type: ignore
except Exception:  # pragma: no cover
    class _DummyEngine:
        def compute(self, confidence: float, residual_trend: float, regime_stability: float):
            return {'gbrt': 0.5, 'retrieval': 0.5}
    def get_weighting_engine():  # type: ignore
        return _DummyEngine()
from src.ml.quality_targets import get_quality_targets

try:
    from prometheus_client import REGISTRY  # type: ignore
except Exception:  # pragma: no cover
    REGISTRY = None

_DEF_LONG_WINDOW = 1800  # 30m in seconds for baseline reference

def _extract_metric_value(name: str) -> float:
    if REGISTRY is None:
        return 0.0
    try:
        for fam in REGISTRY.collect():  # type: ignore[attr-defined]
            if fam.name == name:
                for sample in fam.samples:  # type: ignore[attr-defined]
                    if sample.name == name:
                        return float(sample.value)
    except Exception:
        return 0.0
    return 0.0

def compute_drift_components(index: str, horizon: int) -> Dict[str, Any]:
    index_u = index.upper()
    horizon = int(horizon)
    qt = get_quality_targets()
    # Residual stats (includes decay p95)
    stats = get_residual_stats(index_u, [horizon])[0]
    tail_ratio = 0.0
    long_baseline = stats.p95 if stats.p95 > 0 else 0.0001
    tail_ratio = stats.p95_decay / long_baseline if long_baseline else 0.0
    trend_ratio = stats.trend_ratio
    residual_trend_live = get_residual_trend(index=index_u, horizon=horizon)
    # Burn rate from recording rule if metric present
    burn_rate = _extract_metric_value('g6_ml_residual_tail_burn:short_long')
    # Weights divergence (use current weighting engine on neutral assumptions)
    weights = get_weighting_engine().compute(confidence=0.75, residual_trend=residual_trend_live, regime_stability=0.8)
    weight_divergence = abs(weights.get('gbrt', 0) - weights.get('retrieval', 0))
    # Regime class metric if exposed
    regime_class = _extract_metric_value('g6_ml_residual_health:class')
    # Retrain signal smoothed
    retrain_signal = _extract_metric_value('g6_ml_retrain_signal:smooth_5m')
    improve_target = qt.mae_p95_improve_pct
    attribution = {
        'index': index_u,
        'horizon': horizon,
        'timestamp': time.time(),
        'tail_ratio': tail_ratio,
        'trend_ratio': trend_ratio,
        'burn_rate': burn_rate,
        'weight_divergence': weight_divergence,
        'regime_class': regime_class,
        'retrain_signal': retrain_signal,
        'improve_target_pct': improve_target,
        'tail_ratio_vs_target_gap': round(tail_ratio - (1 - improve_target/100), 6)
    }
    return attribution
