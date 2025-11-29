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
import logging
import json
import os

from src.ml.quality_targets import get_quality_targets

@dataclass
class ResidualStats:
    index: str
    horizon: int
    count: int
    avg: float
    p95: float
    trend_ratio: float

_LOG = logging.getLogger("ml.residuals")
_RESIDUAL_FILE_ENV = "ML_RESIDUAL_HISTORY_FILE"
_FLUSH_INTERVAL_SECONDS = 30

class ResidualStore:
    def __init__(self):
        self._lock = threading.Lock()
        # key -> list[float]; key is (index,horizon)
        self._data: Dict[Tuple[str,int], List[float]] = {}
        self._last_flush = 0.0

    def record(self, index: str, horizon: int, residual: float) -> None:
        key = (index.upper(), int(horizon))
        qt = get_quality_targets()
        depth = qt.residual_depth
        with self._lock:
            lst = self._data.setdefault(key, [])
            lst.append(abs(float(residual)))
            if len(lst) > depth:
                self._data[key] = lst[-depth:]
        # Opportunistic persistence flush
        if os.environ.get(_RESIDUAL_FILE_ENV, ""):
            import time
            now = time.time()
            if now - self._last_flush >= _FLUSH_INTERVAL_SECONDS:
                try:
                    flush_residual_history()
                except Exception as e:  # pragma: no cover
                    _LOG.debug(f"Residual flush failed: {e}")
                self._last_flush = now

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
        try:
            load_residual_history()
        except Exception as e:  # pragma: no cover
            _LOG.debug(f"Residual history load skipped: {e}")
    return _store

# Convenience APIs used by endpoints / weighting engine

def record_residual(index: str, horizon: int, residual: float) -> None:
    get_store().record(index, horizon, residual)

def get_residual_trend(index: str, horizon: int) -> float:
    return get_store().trend_ratio(index, horizon)

def get_residual_stats(index: str, horizons: Iterable[int]) -> List[ResidualStats]:
    return get_store().stats(index, horizons)

# Persistence helpers

def _resolve_path(path: str | None = None) -> str | None:
    p = path or os.environ.get(_RESIDUAL_FILE_ENV, "")
    if not p:
        return None
    return p

def flush_residual_history(path: str | None = None) -> None:
    target = _resolve_path(path)
    if target is None:
        return
    store = get_store()
    payload: Dict[str, Any] = {}
    with store._lock:
        for (idx, hz), arr in store._data.items():
            payload[f"{idx}|{hz}"] = arr
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, target)

def load_residual_history(path: str | None = None, max_keys: int = 10000) -> None:
    source = _resolve_path(path)
    if source is None or not os.path.exists(source):
        return
    with open(source, "r", encoding="utf-8") as f:
        data = json.load(f)
    store = get_store()
    loaded = 0
    with store._lock:
        for key, arr in data.items():
            if loaded >= max_keys:
                break
            try:
                idx, hz_str = key.split("|")
                hz = int(hz_str)
            except Exception:
                continue
            if not isinstance(arr, list):
                continue
            qt = get_quality_targets()
            arr_tail = [abs(float(v)) for v in arr[-qt.residual_depth:]]
            store._data[(idx.upper(), hz)] = arr_tail
            loaded += 1
    if loaded:
        _LOG.debug(f"Loaded residual history keys: {loaded}")
