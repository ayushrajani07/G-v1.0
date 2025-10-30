#!/usr/bin/env python3
"""StatusReader: unified, cached access to runtime_status.json

Backed by src.data_access.unified_source.UnifiedDataSource and offering
simple, consistent helpers for commonly accessed sections.
"""

from __future__ import annotations

import os
import json
import threading
from datetime import UTC, datetime
from typing import Any, TypeVar, overload
import time as _t

# Phase 2: Centralized environment variable access
from src.config.env_config import EnvConfig
from src.data_access.unified_source import DataSourceConfig, UnifiedDataSource
from pathlib import Path
from .csv_cache import read_json_cached

T = TypeVar("T")


class StatusReader:
    _singleton: StatusReader | None = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls, status_path: str | None = None) -> StatusReader:
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = StatusReader(status_path)
            elif status_path:
                cls._singleton._update_path(status_path)
            return cls._singleton

    def __init__(self, status_path: str | None = None) -> None:
        self._path = self._resolve_path(status_path)
        self._uds = UnifiedDataSource()
        # Configure data source to our preferred path; keep other defaults
        cfg = DataSourceConfig(runtime_status_path=self._path)
        self._uds.reconfigure(cfg)

    def _resolve_path(self, path: str | None) -> str:
        if path:
            return path
        env_val = EnvConfig.get_str("G6_RUNTIME_STATUS", "")
        if not env_val:
            return "data/runtime_status.json"
        return str(env_val)

    def _update_path(self, path: str) -> None:
        self._path = path
        cfg = DataSourceConfig(runtime_status_path=self._path)
        self._uds.reconfigure(cfg)

    # ------------ Basic ------------
    def exists(self) -> bool:
        try:
            return os.path.exists(self._path)
        except Exception:
            return False

    def get_raw_status(self) -> dict[str, Any]:
        try:
            data = self._uds.get_runtime_status() or {}
            if not data and self._path and os.path.exists(self._path):
                # Defensive direct read fallback to avoid false negatives from cache layers
                # Use mtime-cached JSON reader to minimize repeated disk I/O under polling.
                try:
                    obj = read_json_cached(Path(self._path))
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    pass
            return data
        except Exception:
            return {}

    # ------------ Common sections ------------
    def get_cycle_data(self) -> dict[str, Any]:
        try:
            d = self._uds.get_cycle_data() or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {"cycle": None, "last_start": None, "last_duration": None, "success_rate": None}

    def get_indices_data(self) -> dict[str, Any]:
        try:
            d = self._uds.get_indices_data() or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {}

    def get_resources_data(self) -> dict[str, Any]:
        try:
            d = self._uds.get_resources_data() or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {"cpu": None, "memory_mb": None}

    def get_provider_data(self) -> dict[str, Any]:
        try:
            d = self._uds.get_provider_data() or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {}

    def get_health_data(self) -> dict[str, Any]:
        try:
            d = self._uds.get_health_data() or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {}

    @overload
    def get_typed(self, path: str) -> Any: ...
    @overload
    def get_typed(self, path: str, default: T) -> T: ...
    def get_typed(self, path: str, default: Any = None) -> Any:
        """Traverse dotted path into the cached status dict.

        If any segment is missing, returns the provided default (None by default).
        No exception is raised; traversal stops at first missing key.
        """
        obj = self.get_raw_status()
        cur: Any = obj
        for part in path.split('.'):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur.get(part)
        return cur

    def get_status_age_seconds(self) -> float | None:
        try:
            st = self.get_raw_status()
            ts = st.get("timestamp") if isinstance(st, dict) else None
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    now = datetime.now(UTC)
                    return (now - dt).total_seconds()
                except Exception:
                    pass
            if self._path and os.path.exists(self._path):
                mtime = os.path.getmtime(self._path)
                return _t.time() - mtime
        except Exception:
            return None
        return None


def get_status_reader(status_path: str | None = None) -> StatusReader:
    return StatusReader.get_instance(status_path)
