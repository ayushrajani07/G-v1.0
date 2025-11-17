"""Rolling MAE & Coverage computation for forecasts.

Refined Phase 10 implementation: deque-based rolling window statistics for p50
mean absolute error and band coverage percentage.

Pipeline:
1. /forecast enqueues evaluation event: (index, horizon, ts_ms, p50, underlying_at_forecast, band_low, band_high).
2. Background daemon (60s interval) evaluates events whose target horizon time elapsed
    (now_ms >= ts_ms + horizon*60_000).
3. For each (index,horizon) maintain deques of last N errors and coverage flags
    (1 if underlying within [band_low, band_high], else 0). N defined by env var.
4. Compute rolling MAE = mean(errors_deque); coverage_pct = mean(flags_deque)*100.
5. Export gauges via Prometheus: g6_forecast_mae, g6_forecast_coverage_pct.

Environment Variables:
- G6_ROLLING_MAE_ENABLE=1: Enable evaluator thread & logging.
- G6_ROLLING_MAE_MAX_EVENTS=5000: Cap pending unevaluated event queue size.
- G6_ROLLING_MAE_WINDOW=500: Rolling window length for MAE & coverage deques.

Notes / Limitations:
- Underlying at evaluation approximated by latest inferred value (best-effort); fallback to underlying at forecast time if unavailable.
- No persistence; window resets on process restart.
- Clock drift / delayed evaluation may slightly shift horizon alignment for large horizons; acceptable for rolling monitoring.
"""
Thread-safety: protected by _LOCK.
Persistence: none (in-memory only). Reset on process restart.
"""
from __future__ import annotations

import os, time, threading, logging
from typing import Dict, List, Tuple
from collections import deque

_LOG = logging.getLogger(__name__)

_ENABLE = os.environ.get("G6_ROLLING_MAE_ENABLE", "1") == "1"
_MAX_EVENTS = int(os.environ.get("G6_ROLLING_MAE_MAX_EVENTS", "5000"))
_WINDOW_SIZE = int(os.environ.get("G6_ROLLING_MAE_WINDOW", "500"))

_EVENTS: List[Tuple[str,int,int,float,float,float,float]] = []  # pending evaluation events
_LOCK = threading.Lock()
_ERRORS: Dict[Tuple[str,int], deque] = {}
_COVER_FLAGS: Dict[Tuple[str,int], deque] = {}
_STARTED = False

def log_forecast_event(index: str, horizon: int, ts_ms: int, p50: float, underlying: float, band_low: float, band_high: float) -> None:
    """Log forecast event for future MAE evaluation."""
    if not _ENABLE:
        return
    if p50 == 0.0:
        return  # Skip zero forecasts (likely placeholder)
    if band_low > band_high:
        # swap if inverted
        band_low, band_high = band_high, band_low
    with _LOCK:
        if len(_EVENTS) >= _MAX_EVENTS:
            _EVENTS.pop(0)
        _EVENTS.append((index.upper(), int(horizon), int(ts_ms), float(p50), float(underlying), float(band_low), float(band_high)))

def _infer_underlying(index: str) -> float:
    """Reuse ensemble router inference for underlying (best-effort)."""
    try:
        from .routes.ensemble import _infer_live_params  # type: ignore
        params = _infer_live_params(index.upper())
        return float(params.get('underlying', 0.0))
    except Exception:
        return 0.0

def _evaluate_ready_events() -> None:
    now_ms = int(time.time() * 1000)
    ready: List[Tuple[str,int,int,float,float,float,float]] = []
    with _LOCK:
        if not _EVENTS:
            return
        remaining: List[Tuple[str,int,int,float,float]] = []
        for evt in _EVENTS:
            idx, horizon, ts_ms, p50, underlying_at_forecast, band_low, band_high = evt
            if now_ms >= ts_ms + (horizon * 60_000):
                ready.append(evt)
            else:
                remaining.append(evt)
        _EVENTS[:] = remaining
    if not ready:
        return
    # Evaluate errors
    for idx, horizon, ts_ms, p50, underlying_at_forecast, band_low, band_high in ready:
        latest_underlying = _infer_underlying(idx)
        if latest_underlying <= 0.0:
            # fallback to underlying at forecast time if current not available
            latest_underlying = underlying_at_forecast
        error = abs(latest_underlying - p50)
        key = (idx, horizon)
        covered = 1 if (band_low <= latest_underlying <= band_high) else 0
        with _LOCK:
            err_deque = _ERRORS.get(key)
            if err_deque is None:
                err_deque = deque(maxlen=_WINDOW_SIZE)
                _ERRORS[key] = err_deque
            cov_deque = _COVER_FLAGS.get(key)
            if cov_deque is None:
                cov_deque = deque(maxlen=_WINDOW_SIZE)
                _COVER_FLAGS[key] = cov_deque
            err_deque.append(error)
            cov_deque.append(covered)
            mae = sum(err_deque) / max(1, len(err_deque))
            coverage_pct = (sum(cov_deque) / max(1, len(cov_deque))) * 100.0
        # Export Prometheus gauge
        try:
            from .prom_metrics import set_forecast_mae, set_forecast_coverage  # type: ignore
            set_forecast_mae(idx, horizon, mae)
            set_forecast_coverage(idx, horizon, coverage_pct)
        except Exception:
            pass

def _loop() -> None:
    _LOG.info("rolling_mae evaluator thread started")
    while True:
        try:
            _evaluate_ready_events()
        except Exception as e:
            _LOG.debug(f"rolling_mae evaluate error: {e}")
        time.sleep(60)  # evaluate once per minute

def ensure_started() -> None:
    global _STARTED
    if not _ENABLE or _STARTED:
        return
    _STARTED = True
    t = threading.Thread(target=_loop, name="rolling_mae_eval", daemon=True)
    t.start()

__all__ = ["log_forecast_event", "ensure_started"]