from __future__ import annotations

import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler

# MEDIUM_IMPACT_OPTIMIZATION: Removed unused type imports (ErrorEvent, FooterSummary, 
# HistoryEntry, HistoryStorage, RollState, StorageSnapshot, StreamRow) since augmentation
# methods that used these types have been removed.

METRIC_LINE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"
    r"\{?(?P<labels>[^}]*)}?\s+"
    r"(?P<value>[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)"
)
LABEL_RE = re.compile(r"(\w+)=\"([^\"]*)\"")

@dataclass
class MetricSample:
    value: float
    labels: dict[str,str]

@dataclass
class ParsedMetrics:
    """Minimal metrics snapshot containing only raw parsed data.
    
    MEDIUM_IMPACT_OPTIMIZATION: Removed 5 fields that were only used by:
    - Deprecated HTML templates (removed in Phase 2)
    - DEBUG endpoints (to be moved to separate module in Opportunity 5)
    
    Removed fields: stream_rows, footer, storage, error_events, missing_core
    This simplification removes ~200 lines of augmentation code.
    """
    ts: float
    raw: dict[str, list[MetricSample]] = field(default_factory=dict)
    age_seconds: float = 0.0
    stale: bool = False

class MetricsCache:
    """Background thread that periodically fetches and parses metrics.
    
    MEDIUM_IMPACT_OPTIMIZATION: Simplified to only cache raw parsed metrics.
    Removed per-index rolling state, history tracking, and augmentation methods
    that were only used by deprecated HTML templates and DEBUG endpoints.
    """
    def __init__(self, endpoint: str, interval: float = 5.0, timeout: float = 1.5) -> None:
        self.endpoint = endpoint.rstrip('/')
        if not self.endpoint.endswith('/metrics'):
            self.endpoint += '/metrics'
        self.interval = interval
        self.timeout = timeout
        self._lock = threading.RLock()
        self._data: ParsedMetrics | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="metrics-cache", daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> ParsedMetrics | None:
        with self._lock:
            if self._data:
                # update age
                self._data.age_seconds = time.time() - self._data.ts
                self._data.stale = self._data.age_seconds > (self.interval * 4)
            return self._data

    def _fetch(self) -> ParsedMetrics:
        ts = time.time()
        try:
            with urllib.request.urlopen(self.endpoint, timeout=self.timeout) as resp:
                text = resp.read().decode('utf-8', errors='replace')
        except Exception as e:
            # Route network/endpoint fetch failure; caller will keep old data
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.NETWORK,
                severity=ErrorSeverity.MEDIUM,
                component="web.metrics_cache",
                function_name="_fetch",
                message=f"Failed to fetch metrics from {self.endpoint}",
                context={"endpoint": self.endpoint, "timeout": self.timeout},
                should_log=False,
            )
            # Raise to let caller's try/except path keep old data
            raise
        parsed: dict[str,list[MetricSample]] = {}
        # DEBUG_CLEANUP_BEGIN: unknown line counter placeholder (no metrics registry in this process)
        unknown_lines = 0
        try:
            for line in text.splitlines():
                if not line or line.startswith('#'):
                    continue
                m = METRIC_LINE_RE.match(line)
                if not m:
                    unknown_lines += 1
                    continue
                name = m.group('name')
                labels_raw = m.group('labels')
                labels: dict[str,str] = {}
                if labels_raw:
                    for lm in LABEL_RE.finditer(labels_raw):
                        labels[lm.group(1)] = lm.group(2)
                try:
                    value = float(m.group('value'))
                except ValueError:
                    continue
                parsed.setdefault(name, []).append(MetricSample(value=value, labels=labels))
        except Exception as e:
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.DATA_PARSING,
                severity=ErrorSeverity.LOW,
                component="web.metrics_cache",
                function_name="_fetch",
                message="Failed parsing metrics response",
                should_log=False,
            )
        pm = ParsedMetrics(ts=ts, raw=parsed)
        # MEDIUM_IMPACT_OPTIMIZATION: Removed _augment_stream, _augment_storage, 
        # _augment_errors methods (~200 lines) - only used by deprecated HTML templates
        # and DEBUG endpoints. DEBUG endpoints can compute on-demand if needed.
        return pm

    def _loop(self) -> None:
        while not self._stop.is_set():
            data = self._safe_fetch_once()
            if data is not None:
                with self._lock:
                    self._data = data
            # Wait even on failure so we don't spin aggressively
            self._stop.wait(self.interval)

    def _safe_fetch_once(self) -> ParsedMetrics | None:
        try:
            return self._fetch()
        except Exception as e:  # pragma: no cover - background safety
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.RESOURCE,
                severity=ErrorSeverity.LOW,
                component="web.metrics_cache",
                function_name="_loop",
                message="Background fetch failed; retaining previous snapshot",
                should_log=False,
            )
            return None
