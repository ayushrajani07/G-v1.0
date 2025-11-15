#!/usr/bin/env python3
"""
Adaptive Circuit Breaker with simple error pattern awareness, jittered backoff,
half-open probing, and optional persistence. Kept lightweight and dependency-free.

Default-off integration: modules can be imported without affecting existing behavior.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any
from pathlib import Path
from src.utils.csv_cache import read_json_cached
from src.error_handling import safe_write_json, safe_read_json, get_error_handler, ErrorCategory, ErrorSeverity


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    def __init__(self, message: str = "Circuit is open", retry_after_seconds: float | None = None):
        self.retry_after_seconds = retry_after_seconds
        if retry_after_seconds is not None:
            message = f"{message}; retry after {retry_after_seconds:.1f}s"
        super().__init__(message)


@dataclass
class BreakerConfig:
    name: str
    failure_threshold: int = 5
    min_reset_timeout: float = 10.0
    max_reset_timeout: float = 300.0
    backoff_factor: float = 2.0
    jitter: float = 0.2
    half_open_successes: int = 1
    persistence_dir: str | None = None


class AdaptiveCircuitBreaker:
    def __init__(self, cfg: BreakerConfig):
        self.cfg = cfg
        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at: float | None = None
        self._current_timeout = max(1.0, float(cfg.min_reset_timeout))
        self._half_open_successes = 0
        self._recent_errors_ts: list[float] = []  # timestamps of recent errors
        self._pfile = None
        if cfg.persistence_dir:
            try:
                os.makedirs(cfg.persistence_dir, exist_ok=True)
                self._pfile = os.path.join(cfg.persistence_dir, f"cb_{cfg.name}.json")
                self._load()
            except Exception:
                self._pfile = None

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def allow(self) -> bool:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._opened_at is None:
                    return False
                elapsed = time.time() - self._opened_at
                if elapsed >= self._current_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_successes = 0
                else:
                    return False
            if self._state == CircuitState.HALF_OPEN:
                # Only allow one probe at a time
                return self._half_open_successes == 0
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= max(1, int(self.cfg.half_open_successes)):
                    self._state = CircuitState.CLOSED
                    self._failures = 0
                    self._opened_at = None
                    self._current_timeout = max(1.0, float(self.cfg.min_reset_timeout))
            else:
                # In CLOSED, decay failures slowly on success
                if self._failures > 0:
                    self._failures -= 1
            self._persist()

    def record_failure(self) -> None:
        with self._lock:
            now = time.time()
            self._recent_errors_ts.append(now)
            # retain recent ~60s window
            cutoff = now - 60.0
            self._recent_errors_ts = [t for t in self._recent_errors_ts if t >= cutoff]
            self._failures += 1
            if self._state == CircuitState.HALF_OPEN:
                # Trip immediately, extend timeout
                self._trip(now)
            elif self._state == CircuitState.CLOSED and self._failures >= max(1, int(self.cfg.failure_threshold)):
                self._trip(now)
            self._persist()

    def _trip(self, now: float) -> None:
        # Adaptive backoff: scale with errors per minute and failures
        errors_per_min = len(self._recent_errors_ts)
        base = max(1.0, float(self.cfg.min_reset_timeout)) * (self.cfg.backoff_factor ** max(0, self._failures - 1))
        # amplify when many errors clustered recently
        amp = 1.0 + min(3.0, errors_per_min / 10.0)
        timeout = base * amp
        # cap and add jitter
        timeout = min(timeout, float(self.cfg.max_reset_timeout))
        if self.cfg.jitter > 0:
            timeout *= (1.0 + (random.random() - 0.5) * 2 * self.cfg.jitter)
            timeout = max(self.cfg.min_reset_timeout, timeout)
        self._current_timeout = timeout
        self._state = CircuitState.OPEN
        self._opened_at = now
        self._half_open_successes = 0

    def execute(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        if not self.allow():
            remaining = None
            with self._lock:
                if self._opened_at is not None:
                    remaining = max(0.0, self._current_timeout - (time.time() - self._opened_at))
            raise CircuitOpenError(retry_after_seconds=remaining)
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    # ---------------- Persistence -----------------
    def _persist(self) -> None:
        if not self._pfile:
            return
        data = {
            "state": self._state.value,
            "failures": self._failures,
            "opened_at": self._opened_at,
            "current_timeout": self._current_timeout,
            "recent_errors": self._recent_errors_ts[-20:],
            "ts": time.time(),
        }
        # Write to temp file first then atomic replace; record FILE_IO errors centrally.
        tmp = f"{self._pfile}.tmp"
        ok = safe_write_json(tmp, data, function_name='adaptive_cb_persist')
        if not ok:
            return
        try:
            os.replace(tmp, self._pfile)
        except Exception as e:  # pragma: no cover - defensive
            try:
                get_error_handler().handle_error(
                    e,
                    category=ErrorCategory.FILE_IO,
                    severity=ErrorSeverity.LOW,
                    component='adaptive_circuit_breaker',
                    function_name='adaptive_cb_atomic_replace',
                    message='persist_replace_failed',
                    context={'path': self._pfile}
                )
            except Exception:
                pass

    def _load(self) -> None:
        if not self._pfile or not os.path.exists(self._pfile):
            return
        # Prefer safe_read_json for FILE_IO error recording; fallback to read_json_cached if parsing fails.
        data = safe_read_json(self._pfile, default=None, function_name='adaptive_cb_load')
        if data is None:
            try:
                data = read_json_cached(Path(self._pfile))
            except Exception:
                return
        if not isinstance(data, dict):
            return
        try:
            self._state = CircuitState(data.get("state", "CLOSED"))
            self._failures = int(data.get("failures", 0))
            self._opened_at = data.get("opened_at")
            self._current_timeout = float(data.get("current_timeout", self.cfg.min_reset_timeout))
            self._recent_errors_ts = list(data.get("recent_errors", []))
        except Exception:
            pass


__all__ = [
    "AdaptiveCircuitBreaker",
    "BreakerConfig",
    "CircuitState",
    "CircuitOpenError",
]
