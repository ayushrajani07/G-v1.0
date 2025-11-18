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
- G6_ROLLING_MAE_PERSIST=1: Enable persistence of window state to JSON file.
- G6_ROLLING_MAE_PERSIST_FILE=metrics/rolling_mae_state.json: Relative path (under project root) for persisted state.
- G6_ROLLING_MAE_DECAY=0: If set to a float 0<alpha<1, use EMA (exponential moving average) instead of simple rolling mean. Gauges reflect EMA; deques retained for debug.
- G6_ROLLING_MAE_HALF_LIFE=0: Optional half-life (in observations) to derive EMA alpha.
    Precedence: if HALF_LIFE > 0 it overrides DECAY. Alpha formula: alpha = 1 - exp(-ln(2)/half_life).
 - G6_ROLLING_MAE_TIME_HALF_LIFE_MINUTES=0: Optional time-based half-life in minutes. If >0 and HALF_LIFE=0 then
     derive observation half-life by dividing minutes by average evaluation cadence per horizon. Approx cadence: each forecast
     evaluation occurs after its horizon elapses; we approximate using the median horizon among active keys or fallback 60.
     Formula: obs_half_life = max(1, round(minutes / max(1, median_horizon_minutes))) then alpha as above.

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
_HALF_LIFE_RAW = os.environ.get("G6_ROLLING_MAE_HALF_LIFE", "0").strip()
_TIME_HALF_LIFE_MIN_RAW = os.environ.get("G6_ROLLING_MAE_TIME_HALF_LIFE_MINUTES", "0").strip()
_DECAY_ALPHA_RAW = os.environ.get("G6_ROLLING_MAE_DECAY", "0").strip()
def _parse_float(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        return 0.0
_HALF_LIFE = _parse_float(_HALF_LIFE_RAW)
_TIME_HALF_LIFE_MIN = _parse_float(_TIME_HALF_LIFE_MIN_RAW)
_DECAY_ALPHA_DIRECT = _parse_float(_DECAY_ALPHA_RAW)
def _compute_median_horizon_active() -> float:
    keys = list(_ERRORS.keys()) or list(_COVER_FLAGS.keys()) or list(_NORM_ERRORS.keys())
    if not keys:
        return 60.0
    hs = sorted([h for _, h in keys])
    n = len(hs)
    if n % 2:
        return float(hs[n//2])
    return (hs[n//2 -1] + hs[n//2]) / 2.0

if _HALF_LIFE > 0:
    import math
    _DECAY_ALPHA = 1.0 - math.exp(-math.log(2.0) / _HALF_LIFE)
elif _TIME_HALF_LIFE_MIN > 0 and _HALF_LIFE <= 0 and _DECAY_ALPHA_DIRECT <= 0:
    # derive observation half-life from time minutes
    median_h = _compute_median_horizon_active()
    obs_half = max(1.0, _TIME_HALF_LIFE_MIN / max(1.0, median_h))
    import math
    _DECAY_ALPHA = 1.0 - math.exp(-math.log(2.0) / obs_half)
    _HALF_LIFE = obs_half  # store derived
else:
    _DECAY_ALPHA = _DECAY_ALPHA_DIRECT
if not (0.0 < _DECAY_ALPHA < 1.0):
    _DECAY_ALPHA = 0.0
_USE_DECAY = _DECAY_ALPHA > 0.0
_PERSIST = os.environ.get("G6_ROLLING_MAE_PERSIST", "1") == "1"
_PERSIST_FILE = os.environ.get("G6_ROLLING_MAE_PERSIST_FILE", "metrics/rolling_mae_state.json")
_LAST_FLUSH = 0.0
_FLUSH_INTERVAL_SEC = 120  # flush at most every 2 minutes

_EVENTS: List[Tuple[str,int,int,float,float,float,float]] = []  # pending evaluation events
_LOCK = threading.Lock()
_ERRORS: Dict[Tuple[str,int], deque] = {}
_COVER_FLAGS: Dict[Tuple[str,int], deque] = {}
_NORM_ERRORS: Dict[Tuple[str,int], deque] = {}
_BAND_WIDTHS: Dict[Tuple[str,int], deque] = {}
_LAST_EVAL_TS: Dict[Tuple[str,int], int] = {}
_EMA_ERROR: Dict[Tuple[str,int], float] = {}
_EMA_COVER: Dict[Tuple[str,int], float] = {}
_EMA_NORM: Dict[Tuple[str,int], float] = {}
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

def _project_root() -> str:
    start = os.path.abspath(__file__)
    cur = os.path.dirname(start)
    while True:
        if os.path.exists(os.path.join(cur, 'pyproject.toml')):
            return cur
        new_cur = os.path.dirname(cur)
        if new_cur == cur:
            return os.getcwd()
        cur = new_cur

def _persist_path() -> str:
    root = _project_root()
    return os.path.join(root, _PERSIST_FILE)

def _save_state(force: bool = False) -> None:
    if not _PERSIST:
        return
    global _LAST_FLUSH
    now = time.time()
    if not force and (now - _LAST_FLUSH) < _FLUSH_INTERVAL_SEC:
        return
    state = {}
    with _LOCK:
        state['use_decay'] = _USE_DECAY
        state['decay_alpha'] = _DECAY_ALPHA
        state['half_life'] = _HALF_LIFE
        state['time_half_life_minutes'] = _TIME_HALF_LIFE_MIN
        for key, dq in _ERRORS.items():
            idx, horizon = key
            state.setdefault('errors', []).append({'index': idx, 'horizon': horizon, 'values': list(dq)})
        for key, dq in _COVER_FLAGS.items():
            idx, horizon = key
            state.setdefault('coverage', []).append({'index': idx, 'horizon': horizon, 'values': list(dq)})
        for key, dq in _NORM_ERRORS.items():
            idx, horizon = key
            state.setdefault('norm_errors', []).append({'index': idx, 'horizon': horizon, 'values': list(dq)})
        for key, dq in _BAND_WIDTHS.items():
            idx, horizon = key
            state.setdefault('band_widths', []).append({'index': idx, 'horizon': horizon, 'values': list(dq)})
        # last evaluation timestamps
        ts_entries = []
        for key, ts in _LAST_EVAL_TS.items():
            idx, horizon = key
            ts_entries.append({'index': idx, 'horizon': horizon, 'last_eval_ts': ts})
        if ts_entries:
            state['last_eval'] = ts_entries
        if _USE_DECAY:
            ema_list = []
            for key, val in _EMA_ERROR.items():
                idx, horizon = key
                ema_list.append({
                    'index': idx,
                    'horizon': horizon,
                    'ema_error': val,
                    'ema_cover': _EMA_COVER.get(key, 0.0),
                    'ema_norm': _EMA_NORM.get(key, 0.0),
                })
            state['ema'] = ema_list
    try:
        path = _persist_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        import json
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f)
        os.replace(tmp, path)
        _LAST_FLUSH = now
    except Exception as e:
        _LOG.debug(f"rolling_mae save_state failed: {e}")

def _load_state() -> None:
    if not _PERSIST:
        return
    path = _persist_path()
    if not os.path.exists(path):
        return
    try:
        import json
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        errors = data.get('errors', [])
        coverage = data.get('coverage', [])
        with _LOCK:
            for item in errors:
                idx = item.get('index')
                horizon = int(item.get('horizon', 0))
                values = item.get('values', [])
                dq = deque(values[-_WINDOW_SIZE:], maxlen=_WINDOW_SIZE)
                _ERRORS[(idx, horizon)] = dq
            for item in coverage:
                idx = item.get('index')
                horizon = int(item.get('horizon', 0))
                values = item.get('values', [])
                dq = deque(values[-_WINDOW_SIZE:], maxlen=_WINDOW_SIZE)
                _COVER_FLAGS[(idx, horizon)] = dq
            for item in data.get('norm_errors', []):
                idx = item.get('index')
                horizon = int(item.get('horizon', 0))
                values = item.get('values', [])
                dq = deque(values[-_WINDOW_SIZE:], maxlen=_WINDOW_SIZE)
                _NORM_ERRORS[(idx, horizon)] = dq
            for item in data.get('band_widths', []):
                idx = item.get('index')
                horizon = int(item.get('horizon', 0))
                values = item.get('values', [])
                dq = deque(values[-_WINDOW_SIZE:], maxlen=_WINDOW_SIZE)
                _BAND_WIDTHS[(idx, horizon)] = dq
            for item in data.get('last_eval', []):
                idx = item.get('index')
                horizon = int(item.get('horizon', 0))
                ts = int(item.get('last_eval_ts', 0))
                _LAST_EVAL_TS[(idx, horizon)] = ts
            if _USE_DECAY:
                for item in data.get('ema', []):
                    idx = item.get('index')
                    horizon = int(item.get('horizon', 0))
                    _EMA_ERROR[(idx, horizon)] = float(item.get('ema_error', 0.0))
                    _EMA_COVER[(idx, horizon)] = float(item.get('ema_cover', 0.0))
                    _EMA_NORM[(idx, horizon)] = float(item.get('ema_norm', 0.0))
        _LOG.info(f"rolling_mae loaded state: errors={len(_ERRORS)} coverage={len(_COVER_FLAGS)}")
    except Exception as e:
        _LOG.debug(f"rolling_mae load_state failed: {e}")

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
        band_width = max(1e-9, band_high - band_low)
        norm_error_val = error / band_width
        with _LOCK:
            if _USE_DECAY:
                prev_err = _EMA_ERROR.get(key, error)
                prev_cov = _EMA_COVER.get(key, covered)
                prev_norm = _EMA_NORM.get(key, norm_error_val)
                _EMA_ERROR[key] = _DECAY_ALPHA * error + (1 - _DECAY_ALPHA) * prev_err
                _EMA_COVER[key] = _DECAY_ALPHA * covered + (1 - _DECAY_ALPHA) * prev_cov
                _EMA_NORM[key] = _DECAY_ALPHA * norm_error_val + (1 - _DECAY_ALPHA) * prev_norm
                # Keep debug deques updated (bounded)
                err_deque = _ERRORS.get(key)
                if err_deque is None:
                    err_deque = deque(maxlen=_WINDOW_SIZE)
                    _ERRORS[key] = err_deque
                cov_deque = _COVER_FLAGS.get(key)
                if cov_deque is None:
                    cov_deque = deque(maxlen=_WINDOW_SIZE)
                    _COVER_FLAGS[key] = cov_deque
                norm_deque = _NORM_ERRORS.get(key)
                if norm_deque is None:
                    norm_deque = deque(maxlen=_WINDOW_SIZE)
                    _NORM_ERRORS[key] = norm_deque
                err_deque.append(error)
                cov_deque.append(covered)
                norm_deque.append(norm_error_val)
                bw_deque = _BAND_WIDTHS.get(key)
                if bw_deque is None:
                    bw_deque = deque(maxlen=_WINDOW_SIZE)
                    _BAND_WIDTHS[key] = bw_deque
                bw_deque.append(band_width)
                mae = _EMA_ERROR[key]
                coverage_pct = _EMA_COVER[key] * 100.0
                norm_error_mean = _EMA_NORM[key]
            else:
                err_deque = _ERRORS.get(key)
                if err_deque is None:
                    err_deque = deque(maxlen=_WINDOW_SIZE)
                    _ERRORS[key] = err_deque
                cov_deque = _COVER_FLAGS.get(key)
                if cov_deque is None:
                    cov_deque = deque(maxlen=_WINDOW_SIZE)
                    _COVER_FLAGS[key] = cov_deque
                norm_deque = _NORM_ERRORS.get(key)
                if norm_deque is None:
                    norm_deque = deque(maxlen=_WINDOW_SIZE)
                    _NORM_ERRORS[key] = norm_deque
                err_deque.append(error)
                cov_deque.append(covered)
                norm_deque.append(norm_error_val)
                bw_deque = _BAND_WIDTHS.get(key)
                if bw_deque is None:
                    bw_deque = deque(maxlen=_WINDOW_SIZE)
                    _BAND_WIDTHS[key] = bw_deque
                bw_deque.append(band_width)
                mae = sum(err_deque) / max(1, len(err_deque))
                coverage_pct = (sum(cov_deque) / max(1, len(cov_deque))) * 100.0
                norm_error_mean = sum(norm_deque) / max(1, len(norm_deque))
            _LAST_EVAL_TS[key] = int(time.time()*1000)
        # Export Prometheus gauge
        try:
            from .prom_metrics import (
                set_forecast_mae,
                set_forecast_coverage,
                set_forecast_norm_error,
            )  # type: ignore
            set_forecast_mae(idx, horizon, mae)
            set_forecast_coverage(idx, horizon, coverage_pct)
            set_forecast_norm_error(idx, horizon, norm_error_mean)
        except Exception:
            pass
    # After processing ready batch, attempt periodic flush
    _save_state()

def _loop() -> None:
    _LOG.info("rolling_mae evaluator thread started")
    _load_state()
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

def force_flush_state() -> dict:
    """Force persistence flush and return summary metadata.

    Returns:
        dict with path, errors_keys, coverage_keys, window_size, persisted (bool)
    """
    if not _PERSIST:
        return {"persisted": False, "reason": "persistence_disabled"}
    _save_state(force=True)
    with _LOCK:
        return {
            "persisted": True,
            "path": _persist_path(),
            "errors_keys": len(_ERRORS),
            "coverage_keys": len(_COVER_FLAGS),
            "window_size": _WINDOW_SIZE,
        }

__all__.append("force_flush_state")

def _percentiles(values: List[float], ps: List[float]) -> Dict[str, float]:
    if not values:
        return {f"p{int(p*100)}": 0.0 for p in ps}
    vs = sorted(values)
    n = len(vs)
    out: Dict[str, float] = {}
    for p in ps:
        if n == 1:
            out[f"p{int(p*100)}"] = vs[0]
            continue
        pos = p * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        val = vs[lo] + (vs[hi] - vs[lo]) * frac
        out[f"p{int(p*100)}"] = float(val)
    return out

def get_metric_comparison(index: str | None = None, horizon: int | None = None) -> dict:
    """Return rolling vs EMA metrics with optional filtering and percentiles.

    Args:
        index: optional index filter (case-insensitive)
        horizon: optional horizon filter
    """
    out = {"use_decay": _USE_DECAY, "decay_alpha": _DECAY_ALPHA, "entries": []}
    with _LOCK:
        keys = set(_ERRORS.keys()) | set(_COVER_FLAGS.keys()) | set(_NORM_ERRORS.keys()) | set(_BAND_WIDTHS.keys())
        if index is not None:
            idxu = index.upper()
            keys = {k for k in keys if k[0] == idxu}
        if horizon is not None:
            keys = {k for k in keys if k[1] == horizon}
        for key in sorted(keys):
            idx, h = key
            err_dq = _ERRORS.get(key, [])
            cov_dq = _COVER_FLAGS.get(key, [])
            norm_dq = _NORM_ERRORS.get(key, [])
            bw_dq = _BAND_WIDTHS.get(key, [])
            mae_window = (sum(err_dq) / len(err_dq)) if err_dq else 0.0
            coverage_window_pct = (sum(cov_dq) / len(cov_dq) * 100.0) if cov_dq else 0.0
            norm_error_window = (sum(norm_dq) / len(norm_dq)) if norm_dq else 0.0
            mae_ema = _EMA_ERROR.get(key) if _USE_DECAY else None
            coverage_ema_pct = (_EMA_COVER.get(key) * 100.0) if _USE_DECAY and key in _EMA_COVER else None
            norm_error_ema = _EMA_NORM.get(key) if _USE_DECAY else None
            err_pct = _percentiles(list(err_dq), [0.5, 0.9]) if len(err_dq) >= 5 else {"p50": mae_window, "p90": mae_window}
            norm_pct = _percentiles(list(norm_dq), [0.5, 0.9]) if len(norm_dq) >= 5 else {"p50": norm_error_window, "p90": norm_error_window}
            bw_pct = _percentiles(list(bw_dq), [0.5, 0.9]) if len(bw_dq) >= 5 else {"p50": (bw_dq[-1] if bw_dq else 0.0), "p90": (bw_dq[-1] if bw_dq else 0.0)}
            last_ts = _LAST_EVAL_TS.get(key)
            out["entries"].append({
                "index": idx,
                "horizon": h,
                "mae_window": mae_window,
                "mae_ema": mae_ema,
                "coverage_window_pct": coverage_window_pct,
                "coverage_ema_pct": coverage_ema_pct,
                "norm_error_window": norm_error_window,
                "norm_error_ema": norm_error_ema,
                "count_window": len(err_dq),
                "error_percentiles": err_pct,
                "norm_error_percentiles": norm_pct,
                "band_width_percentiles": bw_pct,
                "last_eval_ts": last_ts,
                "decay_alpha": _DECAY_ALPHA,
                "half_life_obs": _HALF_LIFE,
                "time_half_life_minutes": _TIME_HALF_LIFE_MIN,
            })
    return out

def validate_decay_config() -> dict:
    """Return validation / precedence information for decay configuration."""
    issues = []
    if _HALF_LIFE > 0 and _DECAY_ALPHA_DIRECT > 0:
        issues.append("HALF_LIFE overrides DECAY: DECAY ignored")
    if _TIME_HALF_LIFE_MIN > 0 and _HALF_LIFE > 0:
        issues.append("TIME_HALF_LIFE_MINUTES ignored because HALF_LIFE provided")
    if _TIME_HALF_LIFE_MIN > 0 and _DECAY_ALPHA_DIRECT > 0 and _HALF_LIFE == 0:
        issues.append("TIME_HALF_LIFE_MINUTES ignored because DECAY provided")
    return {
        "decay_alpha": _DECAY_ALPHA,
        "half_life_obs": _HALF_LIFE,
        "time_half_life_minutes": _TIME_HALF_LIFE_MIN,
        "direct_alpha": _DECAY_ALPHA_DIRECT,
        "use_decay": _USE_DECAY,
        "warnings": issues,
    }

__all__.append("validate_decay_config")

__all__.append("get_metric_comparison")