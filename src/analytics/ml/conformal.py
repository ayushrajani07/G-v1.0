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

    @staticmethod
    def _clamp(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))
