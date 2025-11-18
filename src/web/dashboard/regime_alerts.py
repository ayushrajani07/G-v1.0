"""
Weekly Regime Change Alert Pipeline (Phase 10)

Evaluates rolling forecast quality metrics to detect potential regime changes
on a weekly cadence. Emits lightweight Prometheus gauges for alerting rules.

Metrics:
- g6_regime_last_eval_ms{index}: epoch ms of last evaluation per index
- g6_regime_alert_count{index}: count of horizons violating thresholds

Thresholds (env):
- G6_REGIME_COVERAGE_MIN: minimum acceptable coverage percentage (default 75)
- G6_REGIME_NORM_ERROR_P90_MAX: maximum acceptable p90 normalized error (default 0.2)

Scheduling (env):
- G6_REGIME_ALERT_ENABLE: enable scheduler when '1'
- G6_REGIME_EVAL_INTERVAL_SEC: poll interval seconds (default 86400 ~ daily)
- G6_REGIME_ALERT_DAY: weekly day gate (MON..SUN); if set, emit only on this day
  using Asia/Kolkata day-of-week. Empty -> evaluate every interval.
- G6_REGIME_INDICES: comma list of indices (default NIFTY,BANKNIFTY)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

_LOG = logging.getLogger(__name__)

_REGISTRY: Any = None
_METRICS_INITIALIZED = False
_EVAL_THREAD: Optional[threading.Thread] = None
_RUN = False

_LAST_EVAL_MS: Any = None
_ALERT_COUNT: Any = None
_LAST_SUMMARY: Dict[str, Dict[str, Any]] = {}


def _enabled() -> bool:
    return os.environ.get("G6_REGIME_ALERT_ENABLE", "0").strip() == "1"


def _interval_sec() -> int:
    try:
        return max(60, int(os.environ.get("G6_REGIME_EVAL_INTERVAL_SEC", "86400")))
    except Exception:
        return 86400


def _indices() -> list[str]:
    raw = os.environ.get("G6_REGIME_INDICES", "NIFTY,BANKNIFTY")
    return [p.strip().upper() for p in raw.split(',') if p.strip()]


def _alert_day_name() -> str:
    return os.environ.get("G6_REGIME_ALERT_DAY", "").strip().upper()


def _is_gate_day(now_ts: float) -> bool:
    day = _alert_day_name()
    if not day:
        return True
    try:
        tz = ZoneInfo('Asia/Kolkata') if ZoneInfo else None
    except Exception:
        tz = None
    try:
        import datetime as _dt
        dt = _dt.datetime.fromtimestamp(now_ts, tz or _dt.timezone.utc)
        name = dt.strftime('%a').upper()  # MON,TUE,...
        # Normalize to three-letter uppercase
        name = {
            'MONDAY': 'MON', 'TUESDAY': 'TUE', 'WEDNESDAY': 'WED',
            'THURSDAY': 'THU', 'FRIDAY': 'FRI', 'SATURDAY': 'SAT', 'SUNDAY': 'SUN',
        }.get(name, name[:3])
        return name == day[:3]
    except Exception:
        return True  # fail-open


def _init_metrics() -> bool:
    global _METRICS_INITIALIZED, _REGISTRY, _LAST_EVAL_MS, _ALERT_COUNT
    if _METRICS_INITIALIZED:
        return True
    # Only initialize if prom endpoint is enabled to keep footprint minimal
    try:
        from .prom_metrics import _REGISTRY as prom_reg
        if prom_reg is None:
            return False
        _REGISTRY = prom_reg
        from prometheus_client import Gauge  # type: ignore
        _LAST_EVAL_MS = Gauge(
            "g6_regime_last_eval_ms",
            "Epoch ms of last weekly regime evaluation",
            labelnames=["index"],
            registry=_REGISTRY,
        )
        _ALERT_COUNT = Gauge(
            "g6_regime_alert_count",
            "Count of horizons breaching regime thresholds",
            labelnames=["index"],
            registry=_REGISTRY,
        )
        _METRICS_INITIALIZED = True
        return True
    except Exception as e:
        _LOG.debug(f"regime metrics init skipped: {e}")
        return False


def _evaluate_once() -> None:
    if not _init_metrics():
        return
    # Import here to avoid cycles
    try:
        from .rolling_mae import get_metric_comparison, ensure_started  # type: ignore
        ensure_started()
    except Exception as e:
        _LOG.debug(f"regime evaluator missing rolling metrics: {e}")
        return
    try:
        coverage_min = float(os.environ.get("G6_REGIME_COVERAGE_MIN", "75"))
    except Exception:
        coverage_min = 75.0
    try:
        norm_p90_max = float(os.environ.get("G6_REGIME_NORM_ERROR_P90_MAX", "0.2"))
    except Exception:
        norm_p90_max = 0.2

    for idx in _indices():
        try:
            comp = get_metric_comparison(index=idx)
            entries = comp.get("entries", []) if isinstance(comp, dict) else []
            alerts = 0
            breaches: list[Dict[str, Any]] = []
            for ent in entries:
                try:
                    cov = float(ent.get("coverage_window_pct", 0.0))
                    norm_pct = ent.get("norm_error_percentiles", {}) or {}
                    p90 = float(norm_pct.get("p90", ent.get("norm_error_window", 0.0)))
                    h = int(ent.get("horizon", 0))
                    reasons: list[str] = []
                    if cov < coverage_min:
                        reasons.append(f"coverage<{coverage_min}")
                    if p90 > norm_p90_max:
                        reasons.append(f"norm_p90>{norm_p90_max}")
                    triggered = len(reasons) > 0
                    if triggered:
                        alerts += 1
                    breaches.append({
                        "horizon": h,
                        "coverage_window_pct": cov,
                        "norm_error_p90": p90,
                        "triggered": triggered,
                        "reasons": reasons,
                    })
                except Exception:
                    continue
            if _ALERT_COUNT is not None:
                _ALERT_COUNT.labels(index=idx).set(float(alerts))
            if _LAST_EVAL_MS is not None:
                _LAST_EVAL_MS.labels(index=idx).set(time.time() * 1000.0)
            # Store last summary for status endpoint
            _LAST_SUMMARY[idx] = {
                "index": idx,
                "ts_ms": int(time.time() * 1000.0),
                "alerts": int(alerts),
                "total_horizons": len(entries),
                "coverage_min": coverage_min,
                "norm_error_p90_max": norm_p90_max,
                "breaches": breaches,
            }
            _LOG.info(f"regime evaluation idx={idx} alerts={alerts} entries={len(entries)}")
        except Exception as e:
            _LOG.debug(f"regime evaluation failed for {idx}: {e}")


def _loop() -> None:
    _LOG.info("Regime alert scheduler started")
    iv = _interval_sec()
    while _RUN:
        now = time.time()
        try:
            if _is_gate_day(now):
                _evaluate_once()
            else:
                _LOG.info("regime evaluation skipped (not gate day)")
        except Exception as e:
            _LOG.debug(f"regime loop error: {e}")
        # Sleep until next interval or stop
        for _ in range(int(iv)):
            if not _RUN:
                break
            time.sleep(1)
    _LOG.info("Regime alert scheduler stopped")


def start_regime_scheduler() -> None:
    global _RUN, _EVAL_THREAD
    if not _enabled():
        _LOG.info("Regime alerts disabled (G6_REGIME_ALERT_ENABLE!=1)")
        return
    if _EVAL_THREAD is not None and _EVAL_THREAD.is_alive():
        _LOG.info("Regime alert scheduler already running")
        return
    _RUN = True
    t = threading.Thread(target=_loop, name="RegimeAlerts", daemon=True)
    _EVAL_THREAD = t
    t.start()


def stop_regime_scheduler() -> None:
    global _RUN, _EVAL_THREAD
    if _EVAL_THREAD is None or not _EVAL_THREAD.is_alive():
        return
    _RUN = False
    _EVAL_THREAD.join(timeout=5.0)
    _EVAL_THREAD = None


__all__ = [
    "start_regime_scheduler",
    "stop_regime_scheduler",
]

def get_regime_summary(index: Optional[str] = None) -> Dict[str, Any]:
    """Return last computed regime summary.

    If index provided, returns that index's summary or {} if absent.
    If no index provided, returns mapping of all indices to summaries.
    """
    if index:
        return _LAST_SUMMARY.get(index.upper(), {})
    return dict(_LAST_SUMMARY)

__all__.append("get_regime_summary")
