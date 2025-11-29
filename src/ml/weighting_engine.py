"""Adaptive weighting engine for ensemble components.

Computation factors:
- confidence: model composite confidence [0,1]
- residual_trend: recent smoothed residual error ratio (higher => shift weight to retrieval)
- regime_stability: [0,1]; lower stability reduces gbrt weight

Strategy:
1. Base weights from confidence bucket (high vs low) using quality targets improvement goal.
2. Adjust with residual_trend: if residual_trend > threshold (dynamic from mae_p95_improve_pct), damp GBRT weight.
3. Apply regime_stability scaling.
4. Normalize and apply volatility clamp (weight_stddev_max) using an EMA of previous weights.

This is deliberately lightweight until real metrics are wired. Residual trend and regime stability can be injected externally.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Tuple
import math
import time

from src.ml.quality_targets import get_quality_targets

@dataclass
class WeightSnapshot:
    gbrt: float
    retrieval: float
    timestamp: float

class AdaptiveWeightingEngine:
    def __init__(self, alpha: float = 0.4):
        self._prev: WeightSnapshot | None = None
        self._alpha = alpha  # EMA parameter for volatility tracking
        self._ema_gbrt: float | None = None
        self._ema_retrieval: float | None = None

    def _confidence_bucket(self, confidence: float) -> Tuple[float, float]:
        # High-confidence: favor GBRT, Low-confidence: balanced
        if confidence >= 0.75:
            return 0.8, 0.2
        if confidence >= 0.5:
            return 0.65, 0.35
        return 0.55, 0.45

    def _apply_residual_trend(self, g: float, r: float, residual_trend: float, targets) -> Tuple[float, float]:
        # residual_trend expected ~ relative MAE vs baseline (1.0 == baseline)
        # If residual_trend > (1 + improvement pct target/100), shift 5-15% weight from GBRT to retrieval
        threshold = 1 + targets.mae_p95_improve_pct / 100.0
        if residual_trend <= threshold:
            return g, r
        excess = min(residual_trend - threshold, 0.3)  # cap influence
        shift = 0.05 + excess * 0.3  # scaled shift
        g_new = max(g - shift, 0.4)
        r_new = min(r + shift, 0.6)
        return g_new, r_new

    def _apply_regime_stability(self, g: float, r: float, regime_stability: float) -> Tuple[float, float]:
        # Low stability (<0.5) reduces GBRT reliance linearly down to -15%
        if regime_stability >= 0.5:
            return g, r
        reduction = (0.5 - regime_stability) * 0.3  # max 0.15 when stability=0.0
        g_new = max(g - reduction, 0.35)
        r_new = min(r + reduction, 0.65)
        return g_new, r_new

    def _volatility_clamp(self, g: float, r: float, targets) -> Tuple[float, float]:
        # Track EMA and clamp std dev vs EMA to avoid oscillations beyond target
        now = time.time()
        if self._ema_gbrt is None:
            self._ema_gbrt, self._ema_retrieval = g, r
            self._prev = WeightSnapshot(gbrt=g, retrieval=r, timestamp=now)
            return g, r
        # Update EMA
        self._ema_gbrt = self._alpha * g + (1 - self._alpha) * self._ema_gbrt
        self._ema_retrieval = self._alpha * r + (1 - self._alpha) * self._ema_retrieval
        # Compute deviation
        dev_g = abs(g - self._ema_gbrt)
        dev_r = abs(r - self._ema_retrieval)
        max_dev = targets.weight_stddev_max  # using threshold as max allowed instantaneous deviation
        if dev_g > max_dev or dev_r > max_dev:
            # Move weights closer to EMA within allowed band
            g = self._ema_gbrt + math.copysign(max_dev, g - self._ema_gbrt)
            r = self._ema_retrieval + math.copysign(max_dev, r - self._ema_retrieval)
        self._prev = WeightSnapshot(gbrt=g, retrieval=r, timestamp=now)
        return g, r

    def compute(self, confidence: float, residual_trend: float, regime_stability: float) -> Dict[str, float]:
        targets = get_quality_targets()
        g, r = self._confidence_bucket(confidence)
        g, r = self._apply_residual_trend(g, r, residual_trend, targets)
        g, r = self._apply_regime_stability(g, r, regime_stability)
        # Normalize (just in case transforms changed sum)
        total = g + r
        if total <= 0:
            g, r = 0.5, 0.5
            total = 1.0
        g /= total
        r /= total
        g, r = self._volatility_clamp(g, r, targets)
        # Final normalize again
        total = g + r
        g /= total
        r /= total
        return {'gbrt': round(g, 4), 'retrieval': round(r, 4)}

# Global engine instance
_engine: AdaptiveWeightingEngine | None = None

def get_weighting_engine() -> AdaptiveWeightingEngine:
    global _engine
    if _engine is None:
        _engine = AdaptiveWeightingEngine()
    return _engine
