from __future__ import annotations

"""
Simple conformal prediction helper for regression residuals.

Maintains a rolling window of absolute residuals and provides a band radius
corresponding to a desired empirical coverage level.
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable, Optional


@dataclass
class ConformalBand:
    target_coverage: float = 0.8
    window: int = 600
    min_radius: float = 0.0

    def __post_init__(self) -> None:
        self._residuals: Deque[float] = deque(maxlen=int(self.window))

    def update(self, pred: float, actual: float) -> None:
        try:
            r = abs(float(pred) - float(actual))
        except Exception:
            return
        self._residuals.append(r)

    def extend_from_residuals(self, residuals: Iterable[float]) -> None:
        for r in residuals:
            try:
                self._residuals.append(abs(float(r)))
            except Exception:
                continue

    def radius(self, coverage: Optional[float] = None) -> float:
        cov = float(self._clamp(coverage if coverage is not None else self.target_coverage, 0.5, 0.99))
        if not self._residuals:
            return float(self.min_radius)
        s = sorted(self._residuals)
        k = (len(s) - 1) * cov
        f = int(k)
        c = min(f + 1, len(s) - 1)
        q = s[f] if f == c else (s[f] + (s[c] - s[f]) * (k - f))
        return float(max(q, self.min_radius))

    def coverage_estimate(self, radius: float) -> float:
        if not self._residuals:
            return 0.0
        r = float(max(radius, 0.0))
        inside = sum(1 for x in self._residuals if x <= r)
        return inside / len(self._residuals)

    def adapt_target_coverage(self, current_norm_error: float, target_norm_error: float = 0.1) -> float:
        """Adapt target coverage based on normalized error trend.
        
        If current error is high relative to target, widen bands (increase coverage).
        If current error is low, narrow bands (decrease coverage).
        
        Args:
            current_norm_error: Recent normalized error (e.g. MAE / band_width)
            target_norm_error: Desired normalized error level
            
        Returns:
            New target coverage (clamped 0.5-0.99)
        """
        # Simple P-controller logic
        error_ratio = current_norm_error / max(1e-6, target_norm_error)
        
        # If error is 2x target, we want to increase coverage significantly
        # If error is 0.5x target, we can decrease coverage
        
        # Adjustment factor: 
        # ratio > 1 -> increase coverage
        # ratio < 1 -> decrease coverage
        
        # Dampening factor to prevent oscillation
        k = 0.05
        
        delta = (error_ratio - 1.0) * k
        new_coverage = self.target_coverage + delta
        
        self.target_coverage = self._clamp(new_coverage, 0.5, 0.99)
        return self.target_coverage

    @staticmethod
    def _clamp(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))
