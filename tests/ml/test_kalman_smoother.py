from __future__ import annotations

import math
import random

from src.analytics.ml.kalman import Kalman1D  # type: ignore


def test_kalman_reduces_variance():
    random.seed(123)
    # Create a slowly varying underlying signal plus noise
    base = [100.0 + math.sin(i / 10.0) * 2.0 for i in range(300)]
    noisy = [x + random.gauss(0, 2.0) for x in base]

    kf = Kalman1D(q=0.5, r=4.0, x0=None, p0=1.0)
    kf.reset()
    smooth = [kf.update(z) for z in noisy]

    def var(xs):
        m = sum(xs) / len(xs)
        return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)

    # Variance of smoothed series should be less than noisy
    assert var(smooth) < var(noisy)
