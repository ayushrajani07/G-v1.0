from __future__ import annotations

from typing import Sequence, Tuple, Dict, Any, List

from .interfaces import PathForecaster


class HybridPathForecaster(PathForecaster):
    """Stub hybrid forecaster.

    Placeholder implementation that returns a naive flat path using last observed tp
    and fixed-width quantile bands. This keeps the API working while we build
    retrieval and transformer prior stages.
    """

    def __init__(self, *, band_pct: float = 0.05) -> None:
        # +/- percentage around median for q10/q90
        self.band_pct = float(max(0.0, band_pct))

    def forecast_path(
        self,
        recent_window: Sequence[Sequence[float]],
        *,
        context: Dict[str, Any],
        quantiles: Sequence[float] = (0.1, 0.5, 0.9),
        horizon_minutes: int = 60,
        bucket_ms: int = 60_000,
    ) -> Tuple[Sequence[int], Dict[float, Sequence[float]]]:
        # Determine base level from context or recent_window; fall back to 0.0
        last_tp = float(context.get("last_tp", 0.0))
        now_ms = int(context.get("now_ms") or 0)
        # Build future timeline
        H = max(1, int(horizon_minutes))
        times = [now_ms + (i + 1) * bucket_ms for i in range(H)]
        # Flat path median
        qmap: Dict[float, Sequence[float]] = {}
        med = tuple(last_tp for _ in range(H))
        for q in quantiles:
            if abs(q - 0.5) < 1e-9:
                qmap[q] = med
            else:
                band = self.band_pct * max(1.0, abs(last_tp))
                if q < 0.5:
                    qmap[q] = tuple(last_tp - band for _ in range(H))
                else:
                    qmap[q] = tuple(last_tp + band for _ in range(H))
        return times, qmap
