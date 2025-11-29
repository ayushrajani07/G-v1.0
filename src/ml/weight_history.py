"""Weight history tracking for volatility computation.

Stores recent ensemble weights per (index,horizon) in a bounded deque.
Volatility defined as stddev over weights in a lookback window (seconds) or
all retained when fewer samples.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Dict, Tuple, Deque, List, Any
import time
import math
import threading
import json
import os
import logging

_LOG = logging.getLogger("ml.weight_history")

_MAX_SAMPLES = 600  # ~10 minutes at 1s frequency; adjust if needed
_FLUSH_INTERVAL_SECONDS = 30
_ENV_FILE = "ML_WEIGHT_HISTORY_FILE"

@dataclass
class _WeightSample:
    ts: float
    gbrt: float
    retrieval: float

class WeightHistoryStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[Tuple[str,int], Deque[_WeightSample]] = {}
        self._last_flush = time.time()

    def record(self, index: str, horizon: int, weights: Dict[str, float]) -> None:
        key = (index.upper(), int(horizon))
        sample = _WeightSample(time.time(), float(weights.get('gbrt', 0.0)), float(weights.get('retrieval', 0.0)))
        with self._lock:
            dq = self._data.setdefault(key, deque(maxlen=_MAX_SAMPLES))
            dq.append(sample)
            # Opportunistic periodic flush
            if time.time() - self._last_flush >= _FLUSH_INTERVAL_SECONDS:
                try:
                    flush_history()
                except Exception as e:  # pragma: no cover
                    _LOG.debug(f"Flush failed: {e}")
                self._last_flush = time.time()

    def volatility(self, index: str, horizon: int, window_seconds: int = 900) -> Tuple[float,float]:
        key = (index.upper(), int(horizon))
        cutoff = time.time() - window_seconds
        with self._lock:
            samples = [s for s in self._data.get(key, []) if s.ts >= cutoff]
        if len(samples) < 2:
            return 0.0, 0.0
        g_values = [s.gbrt for s in samples]
        r_values = [s.retrieval for s in samples]
        def _std(vals: List[float]) -> float:
            mean = sum(vals)/len(vals)
            var = sum((v-mean)**2 for v in vals)/len(vals)
            return math.sqrt(var)
        return _std(g_values), _std(r_values)

_store: WeightHistoryStore | None = None

def get_store() -> WeightHistoryStore:
    global _store
    if _store is None:
        _store = WeightHistoryStore()
        # Attempt load on first access
        try:
            load_history()
        except Exception as e:  # pragma: no cover
            _LOG.debug(f"Load history skipped: {e}")
    return _store

def record_weights(index: str, horizon: int, weights: Dict[str,float]) -> None:
    get_store().record(index, horizon, weights)

def get_weight_volatility(index: str, horizon: int, window_seconds: int = 900) -> Tuple[float,float]:
    return get_store().volatility(index, horizon, window_seconds)

# Persistence helpers

def _resolve_path(path: str | None = None) -> str | None:
    p = path or os.environ.get(_ENV_FILE, "")
    if not p:
        return None
    return p

def flush_history(path: str | None = None) -> None:
    """Write current weight samples to JSON file.

    Format: {"index|horizon": [[ts, gbrt, retrieval], ...]}
    """
    target = _resolve_path(path)
    if target is None:
        return
    store = get_store()
    with store._lock:
        payload: Dict[str, Any] = {}
        for (idx, hz), dq in store._data.items():
            payload[f"{idx}|{hz}"] = [[s.ts, s.gbrt, s.retrieval] for s in dq]
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, target)

def load_history(path: str | None = None, max_age_seconds: int = 3600) -> None:
    """Load weight samples from JSON file, ignoring entries older than max_age_seconds."""
    source = _resolve_path(path)
    if source is None or not os.path.exists(source):
        return
    now = time.time()
    with open(source, "r", encoding="utf-8") as f:
        data = json.load(f)
    store = get_store()
    loaded = 0
    with store._lock:
        for key, rows in data.items():
            try:
                idx, hz_str = key.split("|")
                hz = int(hz_str)
            except Exception:
                continue
            dq = store._data.setdefault((idx, hz), deque(maxlen=_MAX_SAMPLES))
            for ts, g, r in rows:
                if now - float(ts) <= max_age_seconds:
                    dq.append(_WeightSample(float(ts), float(g), float(r)))
                    loaded += 1
    if loaded:
        _LOG.debug(f"Loaded {loaded} weight samples from persistence")
