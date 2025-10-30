"""Lightweight JSON serialization cache for repeated SSE/event payloads.

Purpose:
  Avoid re-serializing identical (event_type, payload) structures for each
  consumer flush within a short window (typically one tick / cycle) to reduce
  CPU and GC pressure at high fan-out.

Design:
  - Key: (event_type, stable_hash(payload)) where stable_hash is a SHA256 of
    canonical JSON (sorted keys, no whitespace) OR a fast fallback repr.
  - Stores resulting UTF-8 encoded JSON bytes.
  - LRU eviction with a configurable max entries.
    - Metrics (if registered via metrics registry under cache group):
       g6_serial_cache_hits_total
       g6_serial_cache_misses_total
       g6_serial_cache_evictions_total
       g6_serial_cache_size
       g6_serial_cache_hit_ratio
  - Environment Variables:
       G6_SERIALIZATION_CACHE_MAX (default 1024, 0 disables cache)
       G6_SERIALIZATION_CACHE_HASH=fast|sha256 (default sha256) select hash mode

Thread Safety:
  Simple threading.Lock around operations (publish path already serialized,
  overhead minimal compared to JSON dumps cost).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import cast

from src.config.env_config import EnvConfig
from src.metrics.protocols import CounterLike, GaugeLike

_LOCK = threading.Lock()

try:
    from src.metrics import get_metrics
except Exception:  # pragma: no cover
    from typing import Any as _Any
    def get_metrics() -> _Any | None:
        return None


def _stable_hash(payload: dict, mode: str) -> str:
    if mode == 'fast':
        try:
            # non-cryptographic quick hash (may collide, acceptable for perf hint)
            return str(hash(tuple(sorted(payload.items()))))
        except Exception:
            return str(hash(repr(payload)))
    # sha256 canonical json
    try:
        blob = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    except Exception:
        blob = repr(payload).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


@dataclass
class _Entry:
    key: tuple[str, str]
    data: bytes
    ts: float


class SerializationCache:
    def __init__(self, max_entries: int, hash_mode: str = 'sha256') -> None:
        self.max = max_entries
        self.hash_mode = hash_mode
        self._data: dict[tuple[str,str], _Entry] = {}
        self._order: list[tuple[str,str]] = []  # simple LRU list (small sizes OK)
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        # Typed metric handles (initialized lazily)
        self._m_hits: CounterLike | None = None
        self._m_misses: CounterLike | None = None
        self._m_evictions: CounterLike | None = None
        self._m_size: GaugeLike | None = None
        self._m_hit_ratio: GaugeLike | None = None

    def _touch(self, k: tuple[str,str]) -> None:
        try:
            self._order.remove(k)
        except ValueError:
            pass
        self._order.append(k)

    def get_or_build(self, event_type: str, payload: dict) -> bytes:
        if self.max <= 0:
            # Bypass cache entirely
            try:
                return json.dumps(payload, separators=(',', ':'), sort_keys=False).encode('utf-8')
            except Exception:
                return b'{}'
        h = _stable_hash(payload, self.hash_mode)
        k = (event_type, h)
        ent = self._data.get(k)
        if ent is not None:
            self.hits += 1
            self._touch(k)
            self._export_metrics(hit=True)
            return ent.data
        # Build
        try:
            data = json.dumps(payload, separators=(',', ':'), sort_keys=False).encode('utf-8')
        except Exception:
            data = b'{}'
        self.misses += 1
        self._insert(k, data)
        self._export_metrics(hit=False)
        return data

    def _insert(self, k: tuple[str,str], data: bytes) -> None:
        self._data[k] = _Entry(k, data, time.time())
        self._order.append(k)
        if len(self._data) > self.max:
            # Evict oldest
            old = self._order.pop(0)
            if old in self._data:
                del self._data[old]
                self.evictions += 1

    def _export_metrics(self, *, hit: bool | None) -> None:
        m = get_metrics()
        if not m:
            return
        # Lazily register typed metric handles once
        try:
            if self._m_hits is None or self._m_misses is None or self._m_size is None or self._m_hit_ratio is None:
                reg = getattr(m, '_register', None)
                if callable(reg):
                    from prometheus_client import Counter as _C
                    from prometheus_client import Gauge as _G
                    hits = reg(_C, 'g6_serial_cache_hits_total', 'Serialization cache hits')
                    misses = reg(_C, 'g6_serial_cache_misses_total', 'Serialization cache misses')
                    evicts = reg(_C, 'g6_serial_cache_evictions_total', 'Serialization cache evictions')
                    size = reg(_G, 'g6_serial_cache_size', 'Serialization cache current size')
                    ratio = reg(_G, 'g6_serial_cache_hit_ratio', 'Serialization cache hit ratio (0-1)')
                    self._m_hits = cast(CounterLike, hits)
                    self._m_misses = cast(CounterLike, misses)
                    self._m_evictions = cast(CounterLike, evicts)
                    self._m_size = cast(GaugeLike, size)
                    self._m_hit_ratio = cast(GaugeLike, ratio)
        except Exception:
            return

        # Update counters/gauges via typed handles (safe no-ops if still None)
        try:
            if hit is True and self._m_hits is not None:
                self._m_hits.inc()
            elif hit is False and self._m_misses is not None:
                self._m_misses.inc()
            if self._m_size is not None:
                try:
                    self._m_size.set(len(self._data))
                except Exception:
                    pass
            total = self.hits + self.misses
            if total and self._m_hit_ratio is not None:
                try:
                    self._m_hit_ratio.set(self.hits / total)
                except Exception:
                    pass
        except Exception:
            pass


_GLOBAL_CACHE: SerializationCache | None = None


def get_serialization_cache() -> SerializationCache:
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        try:
            max_entries = EnvConfig.get_int('G6_SERIALIZATION_CACHE_MAX', 1024)
        except Exception:
            max_entries = 1024
        mode = EnvConfig.get_str('G6_SERIALIZATION_CACHE_HASH', 'sha256').lower()
        if mode not in ('sha256','fast'):
            mode = 'sha256'
        _GLOBAL_CACHE = SerializationCache(max_entries=max_entries, hash_mode=mode)
    return _GLOBAL_CACHE


def serialize_event(event_type: str, payload: dict) -> bytes:
    """Return cached serialized JSON bytes for (event_type, payload)."""
    cache = get_serialization_cache()
    with _LOCK:
        return cache.get_or_build(event_type, payload)

__all__ = ["serialize_event", "get_serialization_cache", "SerializationCache"]

# Test-only helper (not exported in __all__ to avoid accidental production use)
def _reset_for_tests():  # pragma: no cover - used only in tests
    global _GLOBAL_CACHE
    _GLOBAL_CACHE = None
