"""Phase 9: Enhanced ANN caching with window vectors and disk persistence.

This module provides:
1. ANN Window Vector Cache (in-memory) - ENABLE_ANN_WINDOW_CACHE
2. ANN Disk Cache - ENABLE_ANN_DISK_CACHE with ANN_CACHE_DIR

Metrics exposed:
- g6_ml_ann_cache_hit_ratio
- g6_ml_ann_cache_size
- g6_ml_ann_cache_evictions
- g6_ml_ann_disk_cache_hits
- g6_ml_ann_disk_cache_load_ms
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

_LOG = logging.getLogger("path_forecast.ann_cache")

# In-memory ANN window vector cache
_ANN_WINDOW_CACHE_LOCK = Lock()
_ANN_WINDOW_CACHE: OrderedDict[str, Dict[str, Any]] = OrderedDict()
_ANN_WINDOW_CACHE_MAX_SIZE = int(os.environ.get("ANN_WINDOW_CACHE_MAX_SIZE", "100"))
_ANN_WINDOW_CACHE_HITS = 0
_ANN_WINDOW_CACHE_MISSES = 0
_ANN_WINDOW_CACHE_EVICTIONS = 0

# Disk cache for ANN indices
_ANN_DISK_CACHE_HITS = 0
_ANN_DISK_CACHE_MISSES = 0
_ANN_DISK_CACHE_SAVES = 0


def _env_enabled(key: str) -> bool:
    """Check if environment flag is enabled (1, true, yes, etc.)."""
    val = os.environ.get(key, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _make_cache_key(
    index: str,
    expiry_tag: str,
    offset: str,
    window: int,
    n_today: int,
    space: str,
    dim: Optional[int],
    day_files: Tuple[str, ...],
) -> str:
    """Create a stable cache key for ANN window vectors.
    
    Key components:
    - index, expiry_tag, offset: data source
    - window, n_today: time window parameters
    - space, dim: ANN parameters
    - day_files: file list hash for version tracking
    """
    # Hash the day files list to keep key shorter
    file_hash = hashlib.md5("|".join(day_files).encode()).hexdigest()[:16]
    return f"{index}|{expiry_tag}|{offset}|{window}|{n_today}|{space}|{dim}|{file_hash}"


def _make_disk_cache_key(
    index: str,
    expiry_tag: str,
    offset: str,
    window: int,
    space: str,
    dim: Optional[int],
    model_id: Optional[str] = None,
) -> str:
    """Create a versioned disk cache key.
    
    Includes model_id for versioning (model id + feature set + params).
    """
    mid = model_id or "default"
    return f"{index}_{expiry_tag}_{offset}_w{window}_{space}_d{dim}_{mid}"


def get_ann_windows(
    index: str,
    expiry_tag: str,
    offset: str,
    window: int,
    n_today: int,
    space: str,
    dim: Optional[int],
    day_files: Tuple[str, ...],
) -> Optional[Dict[str, Any]]:
    """Get ANN window vectors from in-memory cache.
    
    Returns:
        Dict with 'ann_windows' and 'ann_day_map' if cached, None otherwise.
    """
    global _ANN_WINDOW_CACHE_HITS, _ANN_WINDOW_CACHE_MISSES
    
    if not _env_enabled("ENABLE_ANN_WINDOW_CACHE"):
        return None
    
    key = _make_cache_key(index, expiry_tag, offset, window, n_today, space, dim, day_files)
    
    with _ANN_WINDOW_CACHE_LOCK:
        if key in _ANN_WINDOW_CACHE:
            _ANN_WINDOW_CACHE.move_to_end(key)
            _ANN_WINDOW_CACHE_HITS += 1
            cached = _ANN_WINDOW_CACHE[key]
            return {
                'ann_windows': list(cached.get('ann_windows', [])),
                'ann_day_map': list(cached.get('ann_day_map', [])),
            }
        
        _ANN_WINDOW_CACHE_MISSES += 1
        return None


def put_ann_windows(
    index: str,
    expiry_tag: str,
    offset: str,
    window: int,
    n_today: int,
    space: str,
    dim: Optional[int],
    day_files: Tuple[str, ...],
    ann_windows: List[List[float]],
    ann_day_map: List[Any],
) -> None:
    """Store ANN window vectors in in-memory cache with LRU eviction."""
    global _ANN_WINDOW_CACHE_EVICTIONS
    
    if not _env_enabled("ENABLE_ANN_WINDOW_CACHE"):
        return
    
    key = _make_cache_key(index, expiry_tag, offset, window, n_today, space, dim, day_files)
    
    with _ANN_WINDOW_CACHE_LOCK:
        _ANN_WINDOW_CACHE[key] = {
            'ann_windows': list(ann_windows),
            'ann_day_map': list(ann_day_map),
        }
        _ANN_WINDOW_CACHE.move_to_end(key)
        
        # LRU eviction
        while len(_ANN_WINDOW_CACHE) > _ANN_WINDOW_CACHE_MAX_SIZE:
            _ANN_WINDOW_CACHE.popitem(last=False)
            _ANN_WINDOW_CACHE_EVICTIONS += 1


def load_ann_index_from_disk(
    index: str,
    expiry_tag: str,
    offset: str,
    window: int,
    space: str,
    dim: Optional[int],
    model_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load ANN index from disk cache.
    
    Returns:
        Dict with 'ann_index', 'ann_day_map', 'metadata' if found, None otherwise.
    """
    global _ANN_DISK_CACHE_HITS, _ANN_DISK_CACHE_MISSES
    
    if not _env_enabled("ENABLE_ANN_DISK_CACHE"):
        return None
    
    cache_dir = os.environ.get("ANN_CACHE_DIR", "")
    if not cache_dir:
        return None
    
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return None
    
    key = _make_disk_cache_key(index, expiry_tag, offset, window, space, dim, model_id)
    index_file = cache_path / f"{key}_index.pkl"
    meta_file = cache_path / f"{key}_meta.json"
    
    if not index_file.exists() or not meta_file.exists():
        _ANN_DISK_CACHE_MISSES += 1
        return None
    
    try:
        t_start = time.perf_counter()
        
        # Load metadata first to validate version
        with open(meta_file, 'r') as f:
            metadata = json.load(f)
        
        # Load pickled index
        with open(index_file, 'rb') as f:
            data = pickle.load(f)
        
        load_ms = int((time.perf_counter() - t_start) * 1000)
        
        _ANN_DISK_CACHE_HITS += 1
        _LOG.info(f"ANN disk cache hit: {key} (loaded in {load_ms}ms)")
        
        return {
            'ann_index': data.get('ann_index'),
            'ann_day_map': data.get('ann_day_map', []),
            'ann_index_mem_bytes': data.get('ann_index_mem_bytes'),
            'metadata': metadata,
            'load_ms': load_ms,
        }
    except Exception as exc:
        _LOG.warning(f"Failed to load ANN disk cache for {key}: {exc}")
        _ANN_DISK_CACHE_MISSES += 1
        return None


def save_ann_index_to_disk(
    index: str,
    expiry_tag: str,
    offset: str,
    window: int,
    space: str,
    dim: Optional[int],
    ann_index: Any,
    ann_day_map: List[Any],
    ann_index_mem_bytes: Optional[int] = None,
    model_id: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Save ANN index to disk cache.
    
    Returns:
        True if saved successfully, False otherwise.
    """
    global _ANN_DISK_CACHE_SAVES
    
    if not _env_enabled("ENABLE_ANN_DISK_CACHE"):
        return False
    
    cache_dir = os.environ.get("ANN_CACHE_DIR", "")
    if not cache_dir:
        return False
    
    cache_path = Path(cache_dir)
    try:
        cache_path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _LOG.warning(f"Failed to create ANN cache directory {cache_dir}: {exc}")
        return False
    
    key = _make_disk_cache_key(index, expiry_tag, offset, window, space, dim, model_id)
    index_file = cache_path / f"{key}_index.pkl"
    meta_file = cache_path / f"{key}_meta.json"
    
    try:
        # Save metadata
        metadata = {
            'index': index,
            'expiry_tag': expiry_tag,
            'offset': offset,
            'window': window,
            'space': space,
            'dim': dim,
            'model_id': model_id,
            'created_at': time.time(),
            'version': '1.0',
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        
        with open(meta_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Save pickled index
        data = {
            'ann_index': ann_index,
            'ann_day_map': list(ann_day_map),
            'ann_index_mem_bytes': ann_index_mem_bytes,
        }
        with open(index_file, 'wb') as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        
        _ANN_DISK_CACHE_SAVES += 1
        _LOG.info(f"ANN disk cache saved: {key}")
        return True
    except Exception as exc:
        _LOG.warning(f"Failed to save ANN disk cache for {key}: {exc}")
        return False


def get_ann_window_cache_stats() -> Dict[str, int]:
    """Get ANN window cache statistics."""
    with _ANN_WINDOW_CACHE_LOCK:
        total_requests = _ANN_WINDOW_CACHE_HITS + _ANN_WINDOW_CACHE_MISSES
        hit_ratio = _ANN_WINDOW_CACHE_HITS / max(1, total_requests)
        
        return {
            'size': len(_ANN_WINDOW_CACHE),
            'hits': _ANN_WINDOW_CACHE_HITS,
            'misses': _ANN_WINDOW_CACHE_MISSES,
            'evictions': _ANN_WINDOW_CACHE_EVICTIONS,
            'hit_ratio': hit_ratio,
        }


def get_ann_disk_cache_stats() -> Dict[str, int]:
    """Get ANN disk cache statistics."""
    total_requests = _ANN_DISK_CACHE_HITS + _ANN_DISK_CACHE_MISSES
    hit_ratio = _ANN_DISK_CACHE_HITS / max(1, total_requests)
    
    return {
        'hits': _ANN_DISK_CACHE_HITS,
        'misses': _ANN_DISK_CACHE_MISSES,
        'saves': _ANN_DISK_CACHE_SAVES,
        'hit_ratio': hit_ratio,
    }


def clear_ann_window_cache() -> None:
    """Clear all ANN window cache entries."""
    with _ANN_WINDOW_CACHE_LOCK:
        _ANN_WINDOW_CACHE.clear()


__all__ = [
    "get_ann_windows",
    "put_ann_windows",
    "load_ann_index_from_disk",
    "save_ann_index_to_disk",
    "get_ann_window_cache_stats",
    "get_ann_disk_cache_stats",
    "clear_ann_window_cache",
]
