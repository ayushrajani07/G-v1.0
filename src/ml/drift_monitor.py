"""Drift Monitoring Placeholder Module (Phase 10)

This stub reserves structure for remote agent implementation.
Remote agent will replace with actual logic for:
- Baseline feature distribution loading (last N days)
- Recent window extraction (intraday rows)
- PSI / KS / mean & variance delta calculation
- Persistence of baselines
- Periodic evaluation thread

Planned environment variables:
- G6_DRIFT_ENABLE=1
- G6_DRIFT_BASELINE_DAYS=30
- G6_DRIFT_RECENT_ROWS=300
- G6_DRIFT_EVAL_INTERVAL_SEC=300

Placeholder functions below return minimal structures.
"""
from __future__ import annotations
from typing import Any, Dict, List

_DEF_BASELINE_DAYS = 30
_DEF_RECENT_ROWS = 300

def compute_feature_distributions(index: str, lookback_days: int = _DEF_BASELINE_DAYS) -> Dict[str, Any]:
    """Placeholder: return empty baseline distribution map."""
    return {"index": index.upper(), "lookback_days": lookback_days, "features": {}}

def calculate_drift_metrics(baseline_window: Dict[str, Any], recent_window: Dict[str, Any]) -> Dict[str, Any]:
    """Placeholder: compute drift metrics (returns empty result)."""
    return {"features": {}, "alerts": 0}

def load_baseline(index: str) -> Dict[str, Any]:  # pragma: no cover
    """Placeholder baseline loader."""
    return {"index": index.upper(), "features": {}, "version": 0}

def save_baseline(index: str, data: Dict[str, Any]) -> None:  # pragma: no cover
    """Placeholder baseline saver (no-op)."""
    return None

def ensure_started() -> None:  # pragma: no cover
    """Placeholder for future evaluator thread start."""
    return None

__all__ = [
    "compute_feature_distributions",
    "calculate_drift_metrics",
    "load_baseline",
    "save_baseline",
    "ensure_started",
]
