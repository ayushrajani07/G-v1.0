"""Canary auto-promotion pipeline skeleton (Phase 13).

Evaluates canary vs baseline residuals and conditionally writes promotion manifest.
Final production integration will trigger config reload & signing.
"""
from __future__ import annotations
from pathlib import Path
import json, statistics
from typing import Sequence, Dict, Any

PROMOTION_DIR = Path('data') / 'canary_promotions'
PROMOTION_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_THRESHOLDS = {
    'p95_improve_min_pct': 5.0,
    'avg_degradation_max_pct': 1.0,
    'outlier_increase_max_pct': 2.0
}

def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(0.95*(len(s)-1))
    return s[idx]

def evaluate_canary(baseline_residuals: Sequence[float], canary_residuals: Sequence[float], thresholds: Dict[str,float] | None = None) -> Dict[str,Any]:
    if len(baseline_residuals) != len(canary_residuals):
        raise ValueError('baseline and canary residual arrays must match length')
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    base_p95 = _p95(baseline_residuals)
    canary_p95 = _p95(canary_residuals)
    p95_improve_pct = 0.0 if base_p95 <= 0 else 100*(base_p95 - canary_p95)/base_p95
    base_avg = statistics.mean(baseline_residuals) if baseline_residuals else 0.0
    canary_avg = statistics.mean(canary_residuals) if canary_residuals else 0.0
    avg_degradation_pct = 0.0 if base_avg <= 0 else 100*(canary_avg - base_avg)/base_avg
    # Outlier counts defined as >p95 baseline
    outlier_base = sum(1 for r in baseline_residuals if r > base_p95)
    outlier_canary = sum(1 for r in canary_residuals if r > base_p95)
    outlier_increase_pct = 0.0 if outlier_base <= 0 else 100*(outlier_canary - outlier_base)/outlier_base
    decision = 'promote'
    if p95_improve_pct < t['p95_improve_min_pct'] or avg_degradation_pct > t['avg_degradation_max_pct'] or outlier_increase_pct > t['outlier_increase_max_pct']:
        decision = 'reject'
    return {
        'baseline_p95': round(base_p95,4),
        'canary_p95': round(canary_p95,4),
        'p95_improve_pct': round(p95_improve_pct,2),
        'baseline_avg': round(base_avg,4),
        'canary_avg': round(canary_avg,4),
        'avg_degradation_pct': round(avg_degradation_pct,2),
        'outlier_increase_pct': round(outlier_increase_pct,2),
        'decision': decision,
        'thresholds': t
    }

def write_promotion_manifest(index: str, model_id: str, evaluation: Dict[str,Any]) -> Path:
    fname = f"promote_{index.upper()}_{model_id}.json"
    path = PROMOTION_DIR / fname
    payload = {
        'index': index.upper(),
        'model_id': model_id,
        'evaluation': evaluation
    }
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return path

__all__ = ['evaluate_canary','write_promotion_manifest']
