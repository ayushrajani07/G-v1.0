"""Weight history tracking for volatility computation.

Stores recent ensemble weights per (index,horizon) in a bounded deque.
Volatility defined as stddev over weights in a lookback window (seconds) or
all retained when fewer samples.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Dict, Tuple, Deque, List
import time
import math
import threading

_MAX_SAMPLES = 600  # ~10 minutes at 1s frequency; adjust if needed

@dataclass
class _WeightSample:
    ts: float
    gbrt: float
    retrieval: float

class WeightHistoryStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[Tuple[str,int], Deque[_WeightSample]] = {}

    def record(self, index: str, horizon: int, weights: Dict[str, float]) -> None:
        key = (index.upper(), int(horizon))
        sample = _WeightSample(time.time(), float(weights.get('gbrt', 0.0)), float(weights.get('retrieval', 0.0)))
        with self._lock:
            dq = self._data.setdefault(key, deque(maxlen=_MAX_SAMPLES))
            dq.append(sample)

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
    return _store

def record_weights(index: str, horizon: int, weights: Dict[str,float]) -> None:
    get_store().record(index, horizon, weights)

def get_weight_volatility(index: str, horizon: int, window_seconds: int = 900) -> Tuple[float,float]:
    return get_store().volatility(index, horizon, window_seconds)
