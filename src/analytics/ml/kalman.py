from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class Kalman1D:
    """Simple 1D Kalman filter for scalar time series.

    State: x (level), P (variance)
    Process model: x_k = x_{k-1} + w,    w ~ N(0, q)
    Measurement:  z_k = x_k + v,         v ~ N(0, r)

    This is a constant-level model (random walk). For many price-like series,
    it provides effective noise reduction without lag catastrophe.

    Parameters
    ----------
    q : float
        Process noise variance (larger -> smoother adapts faster).
    r : float
        Measurement noise variance (larger -> stronger smoothing).
    x0 : Optional[float]
        Initial state estimate; if None, first update uses measurement as x0.
    p0 : float
        Initial state variance.
    """

    q: float = 1.0
    r: float = 4.0
    x0: Optional[float] = None
    p0: float = 1.0

    # Internal state
    _x: Optional[float] = None
    _p: Optional[float] = None

    def reset(self) -> None:
        self._x = self.x0
        self._p = self.p0

    def update(self, z: float) -> float:
        """Incorporate one measurement and return filtered value."""
        # Initialize on first observation
        if self._x is None or self._p is None:
            self._x = float(z if self.x0 is None else self.x0)
            self._p = float(self.p0)

        # Predict
        x_pred = self._x  # random walk: F = 1, no control
        p_pred = self._p + self.q

        # Update
        # Kalman gain K = p_pred / (p_pred + r)
        denom = p_pred + self.r
        k = p_pred / denom if denom > 0 else 0.0
        residual = z - x_pred
        x_new = x_pred + k * residual
        p_new = (1.0 - k) * p_pred

        self._x = x_new
        self._p = p_new
        return x_new

    def state(self) -> Tuple[Optional[float], Optional[float]]:
        return self._x, self._p
