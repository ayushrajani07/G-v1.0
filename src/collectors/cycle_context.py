#!/usr/bin/env python3
"""Cycle context utilities for unified collectors.

Encapsulates shared objects (providers, sinks, metrics) and provides
phase timing instrumentation for lightweight profiling.
"""
from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, field
from typing import Any

# Optional imports
try:
    from src.config.env_config import EnvConfig
except ImportError:
    EnvConfig = None  # type: ignore

logger = logging.getLogger(__name__)

@dataclass
class CycleContext:
    index_params: dict[str, Any]
    providers: Any
    csv_sink: Any
    influx_sink: Any | None = None
    metrics: Any | None = None
    start_wall: float = field(default_factory=time.time)
    start_ts: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    phase_times: dict[str, float] = field(default_factory=dict)
    phase_failures: dict[str, int] = field(default_factory=dict)
    _phase_stack: list[tuple[str, float]] = field(default_factory=list)
    # Phase 10 reliability: per-cycle deduplication set for "no instruments" warnings
    # Key format: f"{index}|{expiry_rule}|{expiry}" (string expiry)
    no_instruments_dedup: set[str] = field(default_factory=set)

    def time_phase(self, name: str):  # context manager
        """Context manager to time a named phase.

        Example:
            with ctx.time_phase('resolve_expiry'):
                ...
        """
        return _PhaseTimer(self, name)

    def record(self, name: str, seconds: float):
        self.phase_times[name] = self.phase_times.get(name, 0.0) + seconds

    def record_failure(self, name: str):
        self.phase_failures[name] = self.phase_failures.get(name, 0) + 1

    def emit_consolidated_log(self):
        if not self.phase_times:
            return
        # Suppress raw PHASE_TIMING when higher-level merged single-emission mode is active
        if EnvConfig is None:
            sh = False
            merge = False
            single = False
        else:
            sh = EnvConfig.get_bool('G6_SINGLE_HEADER_MODE', False)
            merge = EnvConfig.get_bool('G6_PHASE_TIMING_MERGE', False)
            single = EnvConfig.get_bool('G6_PHASE_TIMING_SINGLE_EMIT', False)
        # Always emit consolidated PHASE_TIMING log; higher-level merged lines may also appear.
        try:
            total = sum(self.phase_times.values()) or 0.0
            # Prefer screenshot-style multiline formatting in human mode.
            multiline = False
            try:
                if EnvConfig is not None:
                    multiline = EnvConfig.get_bool('G6_PHASE_TIMING_MULTILINE', EnvConfig.get_bool('G6_HUMAN_MODE', False))
            except (AttributeError, TypeError, ValueError, RuntimeError, KeyError):
                multiline = False

            items = [(phase, secs) for phase, secs in self.phase_times.items()]
            items.sort(key=lambda x: -x[1])

            # Hide metric phases that took ~0 time (common noise in terminal output).
            try:
                hide_zero_metrics = False
                if EnvConfig is not None:
                    hide_zero_metrics = EnvConfig.get_bool(
                        'G6_PHASE_TIMING_HIDE_ZERO_METRICS',
                        EnvConfig.get_bool('G6_HUMAN_MODE', False),
                    )
                if hide_zero_metrics:
                    items = [
                        (p, s)
                        for (p, s) in items
                        if not (('metrics' in str(p).lower()) and (float(s) <= 0.0))
                    ]
            except (AttributeError, TypeError, ValueError, RuntimeError, KeyError):
                pass
            if multiline:
                pad = max((len(p) for p, _ in items), default=0)
                lines = ["PHASE_TIMING"]
                for phase, secs in items:
                    pct = (secs / total * 100.0) if total else 0.0
                    fail = self.phase_failures.get(phase, 0)
                    suffix = f"/F{fail}" if fail else ""
                    lines.append(f"{phase.ljust(pad)}={secs:.3f}s({pct:.1f}%){suffix}")
                lines.append(f"total={total:.3f}s")

                # If the cycle table row is emitted after this block (common in human mode),
                # append the table header here so the numbers are readable mid-scroll.
                try:
                    if EnvConfig is not None and EnvConfig.get_bool('G6_HUMAN_MODE', False):
                        if EnvConfig.get_bool('G6_PHASE_TIMING_APPEND_CYCLE_HEADER', True):
                            m = getattr(self, 'metrics', None)
                            header = getattr(m, '_last_cycle_table_header_line', None) if m is not None else None
                            if isinstance(header, str) and header.strip():
                                lines.append(header)
                except (AttributeError, TypeError, ValueError, RuntimeError, KeyError):
                    pass

                try:
                    if EnvConfig is not None and EnvConfig.get_bool('G6_HUMAN_MODE', False) and EnvConfig.get_bool('G6_HUMAN_SPACERS', True):
                        n = EnvConfig.get_int('G6_HUMAN_SPACER_LINES', 1)
                        for _ in range(max(0, n)):
                            logger.info("")
                except (AttributeError, TypeError, ValueError, RuntimeError, KeyError):
                    pass
                logger.info("\n".join(lines))
            else:
                parts = []
                for phase, secs in items:
                    pct = (secs/total*100.0) if total else 0.0
                    fail = self.phase_failures.get(phase, 0)
                    parts.append(f"{phase}={secs:.3f}s({pct:.1f}%){'/F'+str(fail) if fail else ''}")
                line = "PHASE_TIMING " + " | ".join(parts) + f" | total={total:.3f}s"
                logger.info(line)
        except BaseException as e:  # pragma: no cover
            import asyncio
            if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                raise
            logger.debug("Failed consolidated phase log", exc_info=True)

    def emit_phase_metrics(self):
        if not self.metrics:
            return
        m = self.metrics
        if not hasattr(m, 'phase_duration_seconds'):
            return
        for phase, secs in self.phase_times.items():
            try:
                m.phase_duration_seconds.labels(phase=phase).observe(secs)
            except (AttributeError, TypeError, ValueError, RuntimeError):  # pragma: no cover
                logger.debug("Failed to observe phase duration", exc_info=True)


@dataclass
class ExpiryContext:
    """Per-expiry context bundle.

    Rationale: Many helper calls were passing long positional chains (index_symbol,
    expiry_rule, expiry_date, index_price, collection_time, risk_free_rate, flags).
    This dataclass groups these for cleaner signatures and future extensibility
    (e.g., adding coverage stats, classification status, or memoized ATM strike).

    Only immutable / value-like fields should be added here (mutable dicts like
    enriched_data stay separate to avoid accidental sharing).
    """
    index_symbol: str
    expiry_rule: str
    expiry_date: Any
    collection_time: Any
    index_price: float | int | None
    risk_free_rate: float | None = None
    allow_per_option_metrics: bool = True
    compute_greeks: bool = True
    # Future: coverage_pct: float | None = None, classification: str | None = None

    def as_tags(self) -> dict[str, Any]:  # small convenience for metrics/logs
        return {
            'index': self.index_symbol,
            'expiry_rule': self.expiry_rule,
            'expiry': str(self.expiry_date),
        }

class _PhaseTimer:
    def __init__(self, ctx: CycleContext, name: str):
        self.ctx = ctx; self.name = name; self.t0 = 0.0
    def __enter__(self):
        self.t0 = time.time()
        return self
    def __exit__(self, exc_type, exc, tb):
        dt = time.time() - self.t0
        self.ctx.record(self.name, dt)
        if exc_type is not None:
            self.ctx.record_failure(self.name)
            # Emit failure metric if available
            m = getattr(self.ctx, 'metrics', None)
            if m and hasattr(m, 'phase_failures_total'):
                try:
                    m.phase_failures_total.labels(phase=self.name).inc()
                except (AttributeError, TypeError, ValueError, RuntimeError):  # pragma: no cover
                    pass
        # Do not suppress exceptions
        return False
