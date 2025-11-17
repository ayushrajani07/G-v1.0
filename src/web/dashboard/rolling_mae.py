"""Rolling MAE computation for forecasts.

Phase 10 initial implementation: lightweight in-memory rolling MAE for p50 forecasts.

Approach:
1. When /forecast is called we enqueue an evaluation event containing:
   - index, horizon, timestamp_ms, p50 value, underlying_at_forecast
2. A background daemon thread wakes every 60s, scans events whose horizon window
   has elapsed (now_ms >= timestamp_ms + horizon*60_000) and evaluates error:
      abs(latest_underlying - p50_forecast)
   latest_underlying is inferred using _infer_live_params from ensemble router
   (approximation). This is a coarse first version; later versions can sample
   actual underlying at exact evaluation time or store historical price series.
3. Maintain per (index,horizon) rolling sums and counts; compute MAE = sum/count.
4. Export MAE via Prometheus gauge (set_forecast_mae).

Environment toggles:
- G6_ROLLING_MAE_ENABLE=1 (default) to enable.
- G6_ROLLING_MAE_MAX_EVENTS (default 5000) cap pending queue size.

Thread-safety: protected by _LOCK.
Persistence: none (in-memory only). Reset on process restart.
"""
from __future__ import annotations

import os, time, threading, logging
from typing import Dict, List, Tuple

_LOG = logging.getLogger(__name__)

_ENABLE = os.environ.get("G6_ROLLING_MAE_ENABLE", "1") == "1"
_MAX_EVENTS = int(os.environ.get("G6_ROLLING_MAE_MAX_EVENTS", "5000"))

_EVENTS: List[Tuple[str,int,int,float,float]] = []  # (index,horizon,ts_ms,p50,underlying_at_forecast)
_LOCK = threading.Lock()
_SUMS: Dict[Tuple[str,int], float] = {}
_COUNTS: Dict[Tuple[str,int], int] = {}
_STARTED = False

def log_forecast_event(index: str, horizon: int, ts_ms: int, p50: float, underlying: float) -> None:
    """Log forecast event for future MAE evaluation."""
    if not _ENABLE:
        return
    if p50 == 0.0:
        return  # Skip zero forecasts (likely placeholder)
    with _LOCK:
        if len(_EVENTS) >= _MAX_EVENTS:
            # Drop oldest to make space
            _EVENTS.pop(0)
        _EVENTS.append((index.upper(), int(horizon), int(ts_ms), float(p50), float(underlying)))

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
    ready: List[Tuple[str,int,int,float,float]] = []
    with _LOCK:
        if not _EVENTS:
            return
        remaining: List[Tuple[str,int,int,float,float]] = []
        for evt in _EVENTS:
            idx, horizon, ts_ms, p50, underlying_at_forecast = evt
            if now_ms >= ts_ms + (horizon * 60_000):
                ready.append(evt)
            else:
                remaining.append(evt)
        _EVENTS[:] = remaining
    if not ready:
        return
    # Evaluate errors
    for idx, horizon, ts_ms, p50, underlying_at_forecast in ready:
        latest_underlying = _infer_underlying(idx)
        if latest_underlying <= 0.0:
            # fallback to underlying at forecast time if current not available
            latest_underlying = underlying_at_forecast
        error = abs(latest_underlying - p50)
        key = (idx, horizon)
        with _LOCK:
            _SUMS[key] = _SUMS.get(key, 0.0) + error
            _COUNTS[key] = _COUNTS.get(key, 0) + 1
            mae = _SUMS[key] / max(1, _COUNTS[key])
        # Export Prometheus gauge
        try:
            from .prom_metrics import set_forecast_mae  # type: ignore
            set_forecast_mae(idx, horizon, mae)
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