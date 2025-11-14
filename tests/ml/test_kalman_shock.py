from __future__ import annotations

import math
import random

from src.analytics.ml.kalman import Kalman1D  # type: ignore


def rolling_std(xs, win):
    out = []
    for i in range(len(xs)):
        s = xs[max(0, i - win + 1): i + 1]
        m = sum(s) / len(s)
        v = sum((x - m) ** 2 for x in s) / len(s)
        out.append(math.sqrt(v))
    return out


def test_kalman_shock_spike_exceeds_threshold():
    random.seed(42)
    base = [100.0 + math.sin(i / 10.0) * 1.5 for i in range(200)]
    noisy = [x + random.gauss(0, 0.8) for x in base]
    # Introduce a spike
    noisy[120] += 8.0

    kf = Kalman1D(q=0.3, r=1.0, x0=None, p0=1.0)
    kf.reset()
    smooth = [kf.update(z) for z in noisy]
    residuals = [z - s for z, s in zip(noisy, smooth)]
    stds = rolling_std(residuals, win=60)

    # Shock score at spike point
    idx = 120
    if stds[idx] > 1e-6:
        shock = abs(residuals[idx]) / stds[idx]
        assert shock > 3.0, f"expected shock > 3, got {shock}"
    else:
        # In degenerate case (shouldn't happen here), fail explicitly
        assert False, "std too small for shock calculation"
