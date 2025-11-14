from __future__ import annotations

from typing import Protocol, Sequence, Tuple, Dict, Any


class PathForecaster(Protocol):
    """Protocol for intraday multi-horizon path forecasters.

    Contract per update t:
    - Input: recent window features (shape: W x F) and context (dict) with keys like
      index (str), dte (float), weekday (int), time_of_day_min (int), etc.
    - Output: tuple of (times, qmap) where:
        times: sequence of epoch_ms for future buckets (length H)
        qmap: mapping quantile -> sequence of floats (length H), e.g., {0.1: [...], 0.5: [...], 0.9: [...]}.
    """

    def forecast_path(
        self,
        recent_window: Sequence[Sequence[float]],
        *,
        context: Dict[str, Any],
        quantiles: Sequence[float] = (0.5,),
        horizon_minutes: int = 60,
        bucket_ms: int = 60_000,
    ) -> Tuple[Sequence[int], Dict[float, Sequence[float]]]:
        ...
