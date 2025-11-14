from __future__ import annotations
"""Lightweight in-process caching for per-day TP series used by retrieval/composite forecasters.

Design goals:
- Avoid reparsing the same historical CSV multiple times per request burst.
- Keep dependency surface minimal (pure Python; no pandas/numpy).
- Provide simple metrics (hits/misses, evictions) for observability.
- Allow explicit invalidation (e.g. if backfill scripts rewrite a CSV).

API:
    get_day_tp(root: Path, index: str, expiry_tag: str, offset: str, date_str: str) -> list[float]
        Returns cached list of TP values for the specified day, loading and caching if absent.
    invalidate_day(root: Path, index: str, expiry_tag: str, offset: str, date_str: str) -> None
    stats() -> dict[str, int]

Eviction strategy:
- Size-based LRU capped at MAX_ENTRIES (default 300 day files).
- Each key is (index, expiry_tag, offset, date_str).
- No TTL by default (historical day files immutable during session). Future: add TTL if needed.

Thread safety:
- Uses a single threading.Lock; operations are fast (list copy only). Adequate for current usage.
"""
from pathlib import Path
from typing import Dict, List, Tuple
from threading import Lock
from collections import OrderedDict
from .common import extract_tp as _extract_tp

MAX_ENTRIES = 300

_lock = Lock()
_cache: "OrderedDict[str, List[float]]" = OrderedDict()
_hits = 0
_misses = 0
_evictions = 0


def _make_key(root: Path, index: str, expiry_tag: str, offset: str, date_str: str) -> str:
    """Make a cache key that is unique per root directory and day.

    Including root avoids collisions when multiple datasets/roots are used in the same process
    (e.g., tests creating temp roots). Use resolved absolute path for stability.
    """
    try:
        r = str(root.resolve())
    except Exception:
        r = str(root)
    return f"{r}|{index.upper()}|{expiry_tag}|{offset}|{date_str}"


def get_day_tp(root: Path, index: str, expiry_tag: str, offset: str, date_str: str) -> List[float]:
    """Return TP series for a day via cache.

    Loads CSV: data/g6_data/<INDEX>/<expiry_tag>/<offset>/<YYYY-MM-DD>.csv
    Returns empty list if file missing or unreadable.
    """
    global _hits, _misses, _evictions
    key = _make_key(root, index, expiry_tag, offset, date_str)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            _hits += 1
            return list(_cache[key])  # return a shallow copy to avoid accidental mutation
    # Miss: load outside lock to avoid long blocking
    p = root / index / expiry_tag / str(offset) / f"{date_str}.csv"
    rows: List[dict] = []
    if p.exists():
        try:
            from ..web.dashboard.core.csv_io import load_csv_rows_full as _load
            rows = _load(p)
        except Exception:
            rows = []
    series: List[float] = []
    for r in rows:
        v = _extract_tp(r)
        if isinstance(v, (int, float)):
            series.append(float(v))
    with _lock:
        _misses += 1
        _cache[key] = series
        _cache.move_to_end(key)
        # Evict oldest if over size
        if len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)
            _evictions += 1
    return list(series)


def invalidate_day(root: Path, index: str, expiry_tag: str, offset: str, date_str: str) -> None:
    key = _make_key(root, index, expiry_tag, offset, date_str)
    with _lock:
        _cache.pop(key, None)


def stats() -> Dict[str, int]:
    with _lock:
        return {
            "entries": len(_cache),
            "hits": _hits,
            "misses": _misses,
            "evictions": _evictions,
        }

__all__ = ["get_day_tp", "invalidate_day", "stats"]
