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
    p95_decay: float = 0.0
    trend_ratio: float

_LOG = logging.getLogger("ml.residuals")
_RESIDUAL_FILE_ENV = "ML_RESIDUAL_HISTORY_FILE"
_FLUSH_INTERVAL_SECONDS = 30
_MAX_AGE_ENV = "ML_RESIDUAL_MAX_AGE_SECONDS"
_DECAY_HALF_LIFE_ENV = "ML_RESIDUAL_DECAY_HALF_LIFE_SECONDS"

class ResidualStore:
    def __init__(self):
        self._lock = threading.Lock()
        # key -> list of (ts, residual)
        self._data: Dict[Tuple[str,int], List[Tuple[float,float]]] = {}
        self._last_flush = 0.0

    def _get_config(self) -> Tuple[int, float]:
        qt = get_quality_targets()
        try:
            max_age = int(os.environ.get(_MAX_AGE_ENV, "3600"))
        except Exception:
            max_age = 3600
        try:
            half_life = float(os.environ.get(_DECAY_HALF_LIFE_ENV, "900"))
        except Exception:
            half_life = 900.0
        return max_age, half_life if half_life > 0 else 900.0

    def record(self, index: str, horizon: int, residual: float, ts: float | None = None) -> None:
        import time
        key = (index.upper(), int(horizon))
        qt = get_quality_targets()
        depth = qt.residual_depth
        stamp = ts if ts is not None else time.time()
        with self._lock:
            lst = self._data.setdefault(key, [])
            lst.append((stamp, abs(float(residual))))
            if len(lst) > depth:
                self._data[key] = lst[-depth:]
        # Opportunistic persistence flush
        if os.environ.get(_RESIDUAL_FILE_ENV, ""):
            now = time.time()
            if now - self._last_flush >= _FLUSH_INTERVAL_SECONDS:
                try:
                    flush_residual_history()
                except Exception as e:  # pragma: no cover
                    _LOG.debug(f"Residual flush failed: {e}")
                self._last_flush = now

    def _compute_stats_for(self, index: str, horizon: int) -> ResidualStats:
        import math, time
        key = (index.upper(), int(horizon))
        qt = get_quality_targets()
        short_window = min(30, qt.residual_depth)
        max_age, half_life = self._get_config()
        cutoff = time.time() - max_age
        with self._lock:
            raw = list(self._data.get(key, []))
        # Filter by age
        arr = [(ts, v) for ts, v in raw if ts >= cutoff]
        if not arr:
            return ResidualStats(index=index.upper(), horizon=horizon, count=0, avg=0.0, p95=0.0, trend_ratio=1.0)
        # Exponential decay weight based on age
        now = time.time()
        def weight(ts: float) -> float:
            age = max(now - ts, 0.0)
            # w = 0.5 ** (age / half_life)
            return math.pow(0.5, age / half_life)
        values = [v for _, v in arr]
        weights = [weight(ts) for ts, _ in arr]
        w_sum = sum(weights)
        avg = sum(v * w for v, w in zip(values, weights)) / (w_sum if w_sum > 0 else 1)
        # p95 unweighted on recent window (fair representation of tail)
        s = sorted(values)
        p95 = s[int(0.95 * (len(s) - 1))]
        # Decay-weighted p95 (weighted quantile)
        w_total = sum(weights)
        if w_total <= 0:
            p95_decay = p95
        else:
            # Sort paired values by value ascending for weighted quantile on value distribution
            paired = sorted(zip(values, weights), key=lambda x: x[0])
            cumsum = 0.0
            target = 0.95 * w_total
            p95_decay = paired[-1][0]
            for val, w in paired:
                cumsum += w
                if cumsum >= target:
                    p95_decay = val
                    break
        short_vals = values[-short_window:]
        short_weights = weights[-short_window:]
        sw_sum = sum(short_weights)
        short_avg = sum(v * w for v, w in zip(short_vals, short_weights)) / (sw_sum if sw_sum > 0 else 1)
        trend_ratio = short_avg / avg if avg > 0 else 1.0
        return ResidualStats(index=index.upper(), horizon=horizon, count=len(arr), avg=avg, p95=p95, p95_decay=p95_decay, trend_ratio=trend_ratio)

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

def record_residual(index: str, horizon: int, residual: float, ts: float | None = None) -> None:
    get_store().record(index, horizon, residual, ts=ts)

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
            # Persist as list of [ts, value]
            payload[f"{idx}|{hz}"] = [[ts, v] for ts, v in arr]
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
            parsed: List[Tuple[float,float]] = []
            for entry in arr[-qt.residual_depth:]:
                try:
                    if isinstance(entry, list) and len(entry) == 2:
                        ts_f = float(entry[0])
                        v_f = abs(float(entry[1]))
                        parsed.append((ts_f, v_f))
                    else:  # backward compatibility plain value
                        v_f = abs(float(entry))
                        import time
                        parsed.append((time.time(), v_f))
                except Exception:
                    continue
            store._data[(idx.upper(), hz)] = parsed
            loaded += 1
    if loaded:
        _LOG.debug(f"Loaded residual history keys: {loaded}")
