"""In-memory residuals pipeline for ensemble forecast error tracking.

Endpoints will record residuals (absolute error of p50 vs actual) and expose
stats + trend ratios used by weighting engine.

Trend ratio definition:
  residual_trend = (short_window_avg / long_window_avg) if long_window_avg>0 else 1.0
Short window default: 30 most recent points for (index,horizon)
Long window default: all retained (capped by depth from quality targets).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Iterable, Any
import threading
import statistics

from src.ml.quality_targets import get_quality_targets

@dataclass
class ResidualStats:
    index: str
    horizon: int
    count: int
    avg: float
    p95: float
    trend_ratio: float

class ResidualStore:
    def __init__(self):
        self._lock = threading.Lock()
        # key -> list[float]; key is (index,horizon)
        self._data: Dict[Tuple[str,int], List[float]] = {}

    def record(self, index: str, horizon: int, residual: float) -> None:
        key = (index.upper(), int(horizon))
        qt = get_quality_targets()
        depth = qt.residual_depth
        with self._lock:
            lst = self._data.setdefault(key, [])
            lst.append(abs(float(residual)))
            if len(lst) > depth:
                # keep tail only
                self._data[key] = lst[-depth:]

    def _compute_stats_for(self, index: str, horizon: int) -> ResidualStats:
        key = (index.upper(), int(horizon))
        qt = get_quality_targets()
        short_window = min(30, qt.residual_depth)
        with self._lock:
            arr = list(self._data.get(key, []))
        if not arr:
            return ResidualStats(index=index.upper(), horizon=horizon, count=0, avg=0.0, p95=0.0, trend_ratio=1.0)
        avg = sum(arr)/len(arr)
        # p95 simple approximation using sorted list
        s = sorted(arr)
        p95 = s[int(0.95*(len(s)-1))]
        short = arr[-short_window:]
        short_avg = sum(short)/len(short)
        trend_ratio = short_avg/avg if avg>0 else 1.0
        return ResidualStats(index=index.upper(), horizon=horizon, count=len(arr), avg=avg, p95=p95, trend_ratio=trend_ratio)

    def stats(self, index: str, horizons: Iterable[int]) -> List[ResidualStats]:
        return [self._compute_stats_for(index, h) for h in horizons]

    def trend_ratio(self, index: str, horizon: int) -> float:
        return self._compute_stats_for(index, horizon).trend_ratio

_store: ResidualStore | None = None

def get_store() -> ResidualStore:
    global _store
    if _store is None:
        _store = ResidualStore()
    return _store

# Convenience APIs used by endpoints / weighting engine

def record_residual(index: str, horizon: int, residual: float) -> None:
    get_store().record(index, horizon, residual)

def get_residual_trend(index: str, horizon: int) -> float:
    return get_store().trend_ratio(index, horizon)

def get_residual_stats(index: str, horizons: Iterable[int]) -> List[ResidualStats]:
    return get_store().stats(index, horizons)
