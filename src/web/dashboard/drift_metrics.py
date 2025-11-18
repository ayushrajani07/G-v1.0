"""
Prometheus Drift Metrics for ML Ensemble - Phase 10

Exposes drift monitoring metrics via Prometheus:
- g6_feature_psi: Population Stability Index per feature
- g6_feature_ks_pvalue: KS test p-value per feature
- g6_feature_mean_delta: Mean delta per feature
- g6_feature_var_delta: Variance delta per feature
- g6_feature_drift_flag: Binary alert flag per feature

Part of Phase 10 continuous improvement objectives.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

_LOG = logging.getLogger(__name__)

# Prometheus registry and metrics (initialized lazily)
_REGISTRY: Any = None
_METRICS_INITIALIZED = False
_EVALUATOR_THREAD: Optional[threading.Thread] = None
_EVALUATOR_RUNNING = False

# Metric instances
_FEATURE_PSI: Any = None
_FEATURE_KS_PVALUE: Any = None
_FEATURE_MEAN_DELTA: Any = None
_FEATURE_VAR_DELTA: Any = None
_FEATURE_DRIFT_FLAG: Any = None


def _is_enabled() -> bool:
    """Check if drift metrics are enabled via environment variable."""
    return os.environ.get("G6_DRIFT_ENABLE", "0").strip() == "1"


def _get_eval_interval() -> int:
    """Get drift evaluation interval in seconds from environment."""
    return int(os.environ.get("G6_DRIFT_EVAL_INTERVAL_SEC", "300"))


def _init_metrics() -> bool:
    """Initialize Prometheus drift metrics. Returns True if successful, False otherwise."""
    global _METRICS_INITIALIZED, _REGISTRY
    global _FEATURE_PSI, _FEATURE_KS_PVALUE, _FEATURE_MEAN_DELTA
    global _FEATURE_VAR_DELTA, _FEATURE_DRIFT_FLAG

    if _METRICS_INITIALIZED:
        return True

    if not _is_enabled():
        return False

    try:
        from prometheus_client import Gauge, CollectorRegistry

        # Reuse existing registry if available, otherwise create new one
        try:
            from .prom_metrics import _REGISTRY as existing_registry
            if existing_registry is not None:
                _REGISTRY = existing_registry
                _LOG.info("Reusing existing Prometheus registry for drift metrics")
            else:
                _REGISTRY = CollectorRegistry()
        except (ImportError, AttributeError):
            _REGISTRY = CollectorRegistry()

        # Gauge for PSI (Population Stability Index)
        _FEATURE_PSI = Gauge(
            "g6_feature_psi",
            "Population Stability Index for feature distribution",
            labelnames=["feature", "index"],
            registry=_REGISTRY,
        )

        # Gauge for KS test p-value
        _FEATURE_KS_PVALUE = Gauge(
            "g6_feature_ks_pvalue",
            "Kolmogorov-Smirnov test p-value for feature distribution",
            labelnames=["feature", "index"],
            registry=_REGISTRY,
        )

        # Gauge for mean delta
        _FEATURE_MEAN_DELTA = Gauge(
            "g6_feature_mean_delta",
            "Mean delta (recent - baseline) for feature",
            labelnames=["feature", "index"],
            registry=_REGISTRY,
        )

        # Gauge for variance delta
        _FEATURE_VAR_DELTA = Gauge(
            "g6_feature_var_delta",
            "Variance delta ratio for feature",
            labelnames=["feature", "index"],
            registry=_REGISTRY,
        )

        # Gauge for drift alert flag (0 or 1)
        _FEATURE_DRIFT_FLAG = Gauge(
            "g6_feature_drift_flag",
            "Drift alert flag for feature (1=alert, 0=normal)",
            labelnames=["feature", "index"],
            registry=_REGISTRY,
        )

        _METRICS_INITIALIZED = True
        _LOG.info("Drift Prometheus metrics initialized")
        return True

    except ImportError as e:
        _LOG.warning(f"Failed to initialize drift metrics: {e}")
        return False
    except Exception as e:
        _LOG.error(f"Unexpected error initializing drift metrics: {e}")
        return False


def set_drift_metrics(
    index: str,
    drift_metrics: Dict[str, Dict[str, Any]],
) -> None:
    """Update Prometheus drift metrics for all features.
    
    Args:
        index: Index name (e.g., "NIFTY")
        drift_metrics: Dict mapping feature names to drift metric dicts
    """
    if not _is_enabled():
        return

    _init_metrics()
    
    if not _METRICS_INITIALIZED:
        return
    
    try:
        for feature_name, metrics in drift_metrics.items():
            # Set PSI
            if _FEATURE_PSI is not None:
                _FEATURE_PSI.labels(feature=feature_name, index=index).set(
                    metrics.get("psi", 0.0)
                )
            
            # Set KS p-value
            if _FEATURE_KS_PVALUE is not None:
                _FEATURE_KS_PVALUE.labels(feature=feature_name, index=index).set(
                    metrics.get("ks_pvalue", 1.0)
                )
            
            # Set mean delta
            if _FEATURE_MEAN_DELTA is not None:
                _FEATURE_MEAN_DELTA.labels(feature=feature_name, index=index).set(
                    metrics.get("mean_delta", 0.0)
                )
            
            # Set variance delta
            if _FEATURE_VAR_DELTA is not None:
                _FEATURE_VAR_DELTA.labels(feature=feature_name, index=index).set(
                    metrics.get("var_delta", 0.0)
                )
            
            # Set drift flag (0 or 1)
            if _FEATURE_DRIFT_FLAG is not None:
                _FEATURE_DRIFT_FLAG.labels(feature=feature_name, index=index).set(
                    1.0 if metrics.get("alert_flag", False) else 0.0
                )
    
    except Exception as e:
        _LOG.debug(f"Failed to set drift metrics: {e}")


def _drift_evaluator_loop():
    """Background thread loop for periodic drift evaluation."""
    global _EVALUATOR_RUNNING
    
    _LOG.info("Drift evaluator thread started")
    
    # Get configuration
    eval_interval = _get_eval_interval()
    indices = os.environ.get("G6_DRIFT_INDICES", "NIFTY,BANKNIFTY").split(",")
    indices = [idx.strip().upper() for idx in indices if idx.strip()]
    
    while _EVALUATOR_RUNNING:
        try:
            # Import here to avoid circular dependencies
            from src.ml.drift_monitor import create_drift_monitor_from_env
            
            monitor = create_drift_monitor_from_env()
            
            for index in indices:
                try:
                    # Get or create baseline
                    baseline = monitor.get_or_create_baseline(index)
                    
                    # Get recent window
                    recent = monitor.compute_feature_distributions(
                        index=index,
                        lookback_days=0,  # Use recent_rows
                    )
                    
                    # Calculate drift metrics
                    drift_metrics = monitor.calculate_drift_metrics(baseline, recent)
                    
                    # Update Prometheus gauges
                    set_drift_metrics(index, drift_metrics)
                    
                    _LOG.info(
                        f"Drift evaluation complete for {index}: "
                        f"{len(drift_metrics)} features, "
                        f"{sum(1 for m in drift_metrics.values() if m['alert_flag'])} alerts"
                    )
                
                except Exception as e:
                    _LOG.error(f"Drift evaluation failed for {index}: {e}")
        
        except Exception as e:
            _LOG.error(f"Drift evaluator loop error: {e}")
        
        # Sleep until next evaluation
        time.sleep(eval_interval)
    
    _LOG.info("Drift evaluator thread stopped")


def start_drift_evaluator():
    """Start the drift evaluator background thread."""
    global _EVALUATOR_THREAD, _EVALUATOR_RUNNING
    
    if not _is_enabled():
        _LOG.info("Drift monitoring disabled (G6_DRIFT_ENABLE != 1)")
        return
    
    if _EVALUATOR_THREAD is not None and _EVALUATOR_THREAD.is_alive():
        _LOG.info("Drift evaluator thread already running")
        return
    
    _init_metrics()
    
    _EVALUATOR_RUNNING = True
    _EVALUATOR_THREAD = threading.Thread(
        target=_drift_evaluator_loop,
        name="DriftEvaluator",
        daemon=True,
    )
    _EVALUATOR_THREAD.start()
    _LOG.info("Drift evaluator thread started")


def stop_drift_evaluator():
    """Stop the drift evaluator background thread."""
    global _EVALUATOR_RUNNING, _EVALUATOR_THREAD
    
    if _EVALUATOR_THREAD is None or not _EVALUATOR_THREAD.is_alive():
        _LOG.info("Drift evaluator thread not running")
        return
    
    _LOG.info("Stopping drift evaluator thread...")
    _EVALUATOR_RUNNING = False
    
    # Wait for thread to finish (with timeout)
    _EVALUATOR_THREAD.join(timeout=5.0)
    
    if _EVALUATOR_THREAD.is_alive():
        _LOG.warning("Drift evaluator thread did not stop cleanly")
    else:
        _LOG.info("Drift evaluator thread stopped")
    
    _EVALUATOR_THREAD = None


def get_registry():
    """Get the Prometheus registry (for /metrics endpoint)."""
    _init_metrics()
    return _REGISTRY
