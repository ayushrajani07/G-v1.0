"""ML Quality metrics exporter (Prometheus optional).

Enabled when environment variable ENABLE_ML_QUALITY_METRICS is non-empty.
Exports per (index,horizon):
- g6_ml_ensemble_weight (labels: component)
- g6_ml_residual_trend_ratio
- g6_ml_residual_avg
- g6_ml_residual_p95
- g6_ml_residual_p95_decay (decay-weighted tail)

Usage:
    from src.ml.metrics import push_forecast_metrics
    push_forecast_metrics(index, horizon, weights, residual_trend, residual_avg, residual_p95)

Implementation keeps lazy initialization and silently no-ops if prometheus_client absent.
"""
from __future__ import annotations
import os
from typing import Dict, Any
import logging

_LOG = logging.getLogger("ml.metrics")

_ENABLED = None
_G_WEIGHT = None
_G_RESIDUAL_TREND = None
_G_RESIDUAL_AVG = None
_G_RESIDUAL_P95 = None
_G_RESIDUAL_P95_DECAY = None
_G_TARGET_MAE_P95_IMPROVE_PCT = None
_G_TARGET_WEIGHT_STDDEV_MAX = None
_G_TARGET_REGIME_ALERT_MINUTES = None
_G_DRIFT_CAUSE = None
_G_TAIL_BURN_ACCEL = None

_DEF_LABELS = ("index", "horizon")


def _ensure():
    global _ENABLED, _G_WEIGHT, _G_RESIDUAL_TREND, _G_RESIDUAL_AVG, _G_RESIDUAL_P95, _G_RESIDUAL_P95_DECAY, _G_TARGET_MAE_P95_IMPROVE_PCT, _G_TARGET_WEIGHT_STDDEV_MAX, _G_TARGET_REGIME_ALERT_MINUTES, _G_DRIFT_CAUSE, _G_TAIL_BURN_ACCEL
    if _ENABLED is not None:
        return _ENABLED
    if os.environ.get("ENABLE_ML_QUALITY_METRICS", "").strip() == "":
        _ENABLED = False
        return False
    try:
        from prometheus_client import Gauge  # type: ignore
        _G_WEIGHT = Gauge(
            "g6_ml_ensemble_weight",
            "Adaptive ensemble component weight (0-1)",
            labelnames=["component", *_DEF_LABELS],
        )
        _G_RESIDUAL_TREND = Gauge(
            "g6_ml_residual_trend_ratio",
            "Residual short/long avg ratio ( >1 indicates worsening)",
            labelnames=list(_DEF_LABELS),
        )
        _G_RESIDUAL_AVG = Gauge(
            "g6_ml_residual_avg",
            "Residual long-window average absolute error",
            labelnames=list(_DEF_LABELS),
        )
        _G_RESIDUAL_P95 = Gauge(
            "g6_ml_residual_p95",
            "Residual p95 absolute error",
            labelnames=list(_DEF_LABELS),
        )
        _G_RESIDUAL_P95_DECAY = Gauge(
            "g6_ml_residual_p95_decay",
            "Decay-weighted residual p95 absolute error (recent emphasis)",
            labelnames=list(_DEF_LABELS),
        )
        _G_TARGET_MAE_P95_IMPROVE_PCT = Gauge(
            "g6_ml_target_mae_p95_improve_pct",
            "Target percent improvement for p95 residual vs baseline",
            labelnames=[],
        )
        _G_TARGET_WEIGHT_STDDEV_MAX = Gauge(
            "g6_ml_target_weight_stddev_max",
            "Target maximum component weight volatility (stddev)",
            labelnames=[],
        )
        _G_TARGET_REGIME_ALERT_MINUTES = Gauge(
            "g6_ml_target_regime_alert_minutes",
            "Target minutes threshold for regime alerting",
            labelnames=[],
        )
        _G_DRIFT_CAUSE = Gauge(
            "g6_ml_drift_cause",
            "Drift root cause indicator (one-hot per cause value)",
            labelnames=["cause", *_DEF_LABELS],
        )
        _G_TAIL_BURN_ACCEL = Gauge(
            "g6_ml_tail_burn_accel",
            "Tail burn acceleration (short-long minus 15m avg)",
            labelnames=list(_DEF_LABELS),
        )
        _ENABLED = True
    except Exception as e:
        _LOG.debug(f"Prometheus client unavailable: {e}")
        _ENABLED = False
    return _ENABLED


def push_forecast_metrics(index: str, horizon: int, weights: Dict[str, float], residual_trend: float, residual_avg: float, residual_p95: float, residual_p95_decay: float | None = None) -> None:
    if not _ensure():
        return
    try:
        idx = index.upper()
        h = int(horizon)
        for comp, val in weights.items():
            if _G_WEIGHT is not None:
                _G_WEIGHT.labels(component=comp, index=idx, horizon=h).set(val)
        if _G_RESIDUAL_TREND is not None:
            _G_RESIDUAL_TREND.labels(index=idx, horizon=h).set(residual_trend)
        if _G_RESIDUAL_AVG is not None:
            _G_RESIDUAL_AVG.labels(index=idx, horizon=h).set(residual_avg)
        if _G_RESIDUAL_P95 is not None:
            _G_RESIDUAL_P95.labels(index=idx, horizon=h).set(residual_p95)
        if residual_p95_decay is not None and _G_RESIDUAL_P95_DECAY is not None:
            _G_RESIDUAL_P95_DECAY.labels(index=idx, horizon=h).set(residual_p95_decay)
        # Optional tail burn acceleration metric (caller may precompute and attach)
        accel = weights.get("__tail_burn_accel__")  # sentinel key for accel value
        if accel is not None and _G_TAIL_BURN_ACCEL is not None:
            _G_TAIL_BURN_ACCEL.labels(index=idx, horizon=h).set(float(accel))
    except Exception as e:
        _LOG.debug(f"Failed to push ML quality metrics: {e}")


def push_quality_targets(qt) -> None:
    """Export current quality targets as gauges (no labels)."""
    if not _ensure():
        return
    try:
        if _G_TARGET_MAE_P95_IMPROVE_PCT is not None:
            _G_TARGET_MAE_P95_IMPROVE_PCT.set(qt.mae_p95_improve_pct)
        if _G_TARGET_WEIGHT_STDDEV_MAX is not None:
            _G_TARGET_WEIGHT_STDDEV_MAX.set(qt.weight_stddev_max)
        if _G_TARGET_REGIME_ALERT_MINUTES is not None:
            _G_TARGET_REGIME_ALERT_MINUTES.set(qt.regime_alert_minutes)
    except Exception as e:
        _LOG.debug(f"Failed to push quality target gauges: {e}")

def push_drift_cause(index: str, horizon: int, cause: str) -> None:
    if not _ensure():
        return
    try:
        idx = index.upper(); h = int(horizon)
        # One-hot: set 1 for provided cause, 0 for others (stable, data, model, regime, mixed)
        causes = ["stable","data","model","regime","mixed"]
        for c in causes:
            val = 1 if c == cause else 0
            if _G_DRIFT_CAUSE is not None:
                _G_DRIFT_CAUSE.labels(cause=c, index=idx, horizon=h).set(val)
    except Exception as e:
        _LOG.debug(f"Failed to push drift cause gauge: {e}")
