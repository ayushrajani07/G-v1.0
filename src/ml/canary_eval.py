"""Canary model evaluation harness (Phase 12).

Provides function to compare baseline vs canary predictions producing residual metrics
and improvement signals.
"""
from __future__ import annotations
from typing import Sequence, Dict, Any
import statistics

class CanaryEvalResult:
    def __init__(self, count: int, baseline_p95: float, canary_p95: float, improvement_pct: float, baseline_avg: float, canary_avg: float):
        self.count = count
        self.baseline_p95 = baseline_p95
        self.canary_p95 = canary_p95
        self.improvement_pct = improvement_pct
        self.baseline_avg = baseline_avg
        self.canary_avg = canary_avg

    def to_dict(self) -> Dict[str, Any]:
        return {
            'count': self.count,
            'baseline_p95': round(self.baseline_p95,4),
            'canary_p95': round(self.canary_p95,4),
            'improvement_pct': round(self.improvement_pct,2),
            'baseline_avg': round(self.baseline_avg,4),
            'canary_avg': round(self.canary_avg,4)
        }

def _p95(arr: Sequence[float]) -> float:
    if not arr:
        return 0.0
    s = sorted(arr)
    idx = int(0.95*(len(s)-1))
    return s[idx]

def evaluate_canary(baseline_preds: Sequence[float], canary_preds: Sequence[float], actuals: Sequence[float]) -> CanaryEvalResult:
    if not (len(baseline_preds) == len(canary_preds) == len(actuals)):
        raise ValueError('Input sequences must be same length')
    residuals_base = [abs(b - a) for b,a in zip(baseline_preds, actuals)]
    residuals_canary = [abs(c - a) for c,a in zip(canary_preds, actuals)]
    base_p95 = _p95(residuals_base)
    canary_p95 = _p95(residuals_canary)
    improvement_pct = 0.0
    if base_p95 > 0:
        improvement_pct = 100 * (base_p95 - canary_p95) / base_p95
    return CanaryEvalResult(len(actuals), base_p95, canary_p95, improvement_pct, statistics.mean(residuals_base) if residuals_base else 0.0, statistics.mean(residuals_canary) if residuals_canary else 0.0)
