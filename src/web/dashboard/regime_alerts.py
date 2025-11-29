"""Weekly Regime Change Alert Pipeline (Phase 10 + Drift Autotune)

Evaluates rolling forecast quality metrics to detect potential regime changes
on a daily/weekly cadence. Supports drift detection (MAE / normalized error ratios,
coverage delta) and optional auto-tuning of drift thresholds using historical
percentile baselines.

Metrics:
  - g6_regime_last_eval_ms{index}
  - g6_regime_alert_count{index} (base coverage / norm error breaches)
  - g6_regime_drift_alert_count{index} (drift metric breaches)

Static Thresholds (env):
  - G6_REGIME_COVERAGE_MIN (default 75)
  - G6_REGIME_NORM_ERROR_P90_MAX (default 0.2)
  - G6_REGIME_MAE_DRIFT_RATIO_WARN / G6_REGIME_MAE_DRIFT_RATIO_CRIT (1.5 / 2.0)
  - G6_REGIME_NORM_DRIFT_RATIO_WARN / G6_REGIME_NORM_DRIFT_RATIO_CRIT (1.3 / 1.7)
  - G6_REGIME_COVERAGE_DRIFT_DROP_WARN / G6_REGIME_COVERAGE_DRIFT_DROP_CRIT (-10 / -20) (percentage points)

Autotune (env):
  - G6_REGIME_DRIFT_AUTOTUNE=1 enables percentile-based dynamic thresholds
  - G6_REGIME_DRIFT_WARN_PCTL (default 0.85), G6_REGIME_DRIFT_CRIT_PCTL (0.95)
    applied to drift ratios (upper tail)
  - G6_REGIME_COVERAGE_DRIFT_WARN_PCTL (0.15), G6_REGIME_COVERAGE_DRIFT_CRIT_PCTL (0.05)
    applied to coverage delta (lower tail)
  - Requires >=20 observations for a horizon to activate dynamic thresholds;
    falls back to static env thresholds otherwise.

Scheduling (env):
  - G6_REGIME_ALERT_ENABLE=1 to run scheduler
  - G6_REGIME_EVAL_INTERVAL_SEC (default 86400)
  - G6_REGIME_ALERT_DAY (MON..SUN) optional weekly gating (Asia/Kolkata)
  - G6_REGIME_INDICES (default NIFTY,BANKNIFTY)
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

from .rolling_mae import (
    ensure_started,
    get_metric_comparison,
    get_drift_baselines,
)  # type: ignore

_LOG = logging.getLogger(__name__)

_REGISTRY: Any = None
_METRICS_INITIALIZED = False
_EVAL_THREAD: Optional[threading.Thread] = None
_RUN = False

_LAST_EVAL_MS: Any = None
_ALERT_COUNT: Any = None
_DRIFT_ALERT_COUNT: Any = None
_REGIME_EARLY_WARNING: Any = None
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
        name = dt.strftime('%a').upper()
        name = {
            'MONDAY': 'MON', 'TUESDAY': 'TUE', 'WEDNESDAY': 'WED',
            'THURSDAY': 'THU', 'FRIDAY': 'FRI', 'SATURDAY': 'SAT', 'SUNDAY': 'SUN',
        }.get(name, name[:3])
        return name == day[:3]
    except Exception:
        return True  # fail-open


def _init_metrics() -> bool:
    global _METRICS_INITIALIZED, _REGISTRY, _LAST_EVAL_MS, _ALERT_COUNT, _DRIFT_ALERT_COUNT, _REGIME_EARLY_WARNING
    if _METRICS_INITIALIZED:
        return True
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
        _DRIFT_ALERT_COUNT = Gauge(
            "g6_regime_drift_alert_count",
            "Count of horizons breaching drift thresholds",
            labelnames=["index"],
            registry=_REGISTRY,
        )
        _REGIME_EARLY_WARNING = Gauge(
            "g6_regime_early_warning_score",
            "Composite score for regime shift prediction (0-100)",
            labelnames=["index", "horizon"],
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
    try:
        ensure_started()
    except Exception as e:
        _LOG.debug(f"regime evaluator ensure_started failed: {e}")
        return

    def _f(env: str, default: str) -> float:
        try:
            return float(os.environ.get(env, default))
        except Exception:
            return float(default)

    coverage_min = _f("G6_REGIME_COVERAGE_MIN", "75")
    norm_p90_max = _f("G6_REGIME_NORM_ERROR_P90_MAX", "0.2")

    autotune = os.environ.get("G6_REGIME_DRIFT_AUTOTUNE", "0").strip() == "1"
    warn_pctl = _f("G6_REGIME_DRIFT_WARN_PCTL", "0.85")
    crit_pctl = _f("G6_REGIME_DRIFT_CRIT_PCTL", "0.95")
    warn_cov_low_pctl = _f("G6_REGIME_COVERAGE_DRIFT_WARN_PCTL", "0.15")
    crit_cov_low_pctl = _f("G6_REGIME_COVERAGE_DRIFT_CRIT_PCTL", "0.05")

    mae_warn_static = _f("G6_REGIME_MAE_DRIFT_RATIO_WARN", "1.5")
    mae_crit_static = _f("G6_REGIME_MAE_DRIFT_RATIO_CRIT", "2.0")
    norm_warn_static = _f("G6_REGIME_NORM_DRIFT_RATIO_WARN", "1.3")
    norm_crit_static = _f("G6_REGIME_NORM_DRIFT_RATIO_CRIT", "1.7")
    cover_drop_warn_static = _f("G6_REGIME_COVERAGE_DRIFT_DROP_WARN", "-10")
    cover_drop_crit_static = _f("G6_REGIME_COVERAGE_DRIFT_DROP_CRIT", "-20")

    for idx in _indices():
        try:
            comp = get_metric_comparison(index=idx)
            entries = comp.get("entries", []) if isinstance(comp, dict) else []
            drift_baselines = get_drift_baselines(idx) if autotune else {}
            alerts = 0
            drift_alerts = 0
            breaches: list[Dict[str, Any]] = []
            for ent in entries:
                try:
                    cov = float(ent.get("coverage_window_pct", 0.0))
                    norm_pct = ent.get("norm_error_percentiles", {}) or {}
                    p90 = float(norm_pct.get("p90", ent.get("norm_error_window", 0.0)))
                    h = int(ent.get("horizon", 0))
                    mae_ratio = float(ent.get("mae_drift_ratio", 0.0))
                    norm_ratio = float(ent.get("norm_error_drift_ratio", 0.0))
                    cover_delta = float(ent.get("coverage_drift_delta_pct", 0.0))
                    reasons: list[str] = []
                    if cov < coverage_min:
                        reasons.append(f"coverage<{coverage_min}")
                    if p90 > norm_p90_max:
                        reasons.append(f"norm_p90>{norm_p90_max}")
                    triggered = len(reasons) > 0
                    if triggered:
                        alerts += 1

                    key = (idx, h)
                    base = drift_baselines.get(key, {}) if autotune else {}
                    dyn_mae_warn = dyn_mae_crit = dyn_norm_warn = dyn_norm_crit = None
                    dyn_cover_warn = dyn_cover_crit = None
                    if autotune and base.get("counts", {}).get("mae", 0) >= 20:
                        dyn_mae_warn = base.get("mae_ratio", {}).get(f"p{int(warn_pctl*100)}")
                        dyn_mae_crit = base.get("mae_ratio", {}).get(f"p{int(crit_pctl*100)}")
                    if autotune and base.get("counts", {}).get("norm", 0) >= 20:
                        dyn_norm_warn = base.get("norm_ratio", {}).get(f"p{int(warn_pctl*100)}")
                        dyn_norm_crit = base.get("norm_ratio", {}).get(f"p{int(crit_pctl*100)}")
                    if autotune and base.get("counts", {}).get("coverage", 0) >= 20:
                        dyn_cover_warn = base.get("coverage_delta", {}).get(f"p{int(warn_cov_low_pctl*100)}")
                        dyn_cover_crit = base.get("coverage_delta", {}).get(f"p{int(crit_cov_low_pctl*100)}")

                    mae_warn_eff = dyn_mae_warn if dyn_mae_warn is not None else mae_warn_static
                    mae_crit_eff = dyn_mae_crit if dyn_mae_crit is not None else mae_crit_static
                    norm_warn_eff = dyn_norm_warn if dyn_norm_warn is not None else norm_warn_static
                    norm_crit_eff = dyn_norm_crit if dyn_norm_crit is not None else norm_crit_static
                    cover_warn_eff = dyn_cover_warn if dyn_cover_warn is not None else cover_drop_warn_static
                    cover_crit_eff = dyn_cover_crit if dyn_cover_crit is not None else cover_drop_crit_static

                    drift_reasons: list[str] = []
                    if mae_ratio >= mae_crit_eff:
                        drift_reasons.append(f"mae_ratio>={mae_crit_eff}")
                    elif mae_ratio >= mae_warn_eff:
                        drift_reasons.append(f"mae_ratio>={mae_warn_eff}")
                    if norm_ratio >= norm_crit_eff:
                        drift_reasons.append(f"norm_ratio>={norm_crit_eff}")
                    elif norm_ratio >= norm_warn_eff:
                        drift_reasons.append(f"norm_ratio>={norm_warn_eff}")
                    if cover_delta <= cover_crit_eff:
                        drift_reasons.append(f"cover_drop<={cover_crit_eff}")
                    elif cover_delta <= cover_warn_eff:
                        drift_reasons.append(f"cover_drop<={cover_warn_eff}")
                    drift_triggered = len(drift_reasons) > 0
                    if drift_triggered:
                        drift_alerts += 1

                    breaches.append({
                        "horizon": h,
                        "coverage_window_pct": cov,
                        "norm_error_p90": p90,
                        "mae_drift_ratio": mae_ratio,
                        "norm_error_drift_ratio": norm_ratio,
                        "coverage_drift_delta_pct": cover_delta,
                        "triggered": triggered,
                        "reasons": reasons,
                        "drift_triggered": drift_triggered,
                        "drift_reasons": drift_reasons,
                        "dynamic_thresholds": {
                            "used": autotune,
                            "mae_warn": mae_warn_eff,
                            "mae_crit": mae_crit_eff,
                            "norm_warn": norm_warn_eff,
                            "norm_crit": norm_crit_eff,
                            "coverage_drop_warn": cover_warn_eff,
                            "coverage_drop_crit": cover_crit_eff,
                        },
                    })
                except Exception:
                    continue

            if _ALERT_COUNT is not None:
                _ALERT_COUNT.labels(index=idx).set(float(alerts))
            if _DRIFT_ALERT_COUNT is not None:
                _DRIFT_ALERT_COUNT.labels(index=idx).set(float(drift_alerts))
            if _LAST_EVAL_MS is not None:
                _LAST_EVAL_MS.labels(index=idx).set(time.time() * 1000.0)
            _LAST_SUMMARY[idx] = {
                "index": idx,
                "ts_ms": int(time.time() * 1000.0),
                "alerts": int(alerts),
                "drift_alerts": int(drift_alerts),
                "total_horizons": len(entries),
                "coverage_min": coverage_min,
                "norm_error_p90_max": norm_p90_max,
                "mae_drift_ratio_warn": mae_warn_static,
                "mae_drift_ratio_crit": mae_crit_static,
                "norm_drift_ratio_warn": norm_warn_static,
                "norm_drift_ratio_crit": norm_crit_static,
                "coverage_drift_drop_warn": cover_drop_warn_static,
                "coverage_drift_drop_crit": cover_drop_crit_static,
                "autotune_enabled": autotune,
                "autotune_percentiles": {
                    "warn_pctl": warn_pctl,
                    "crit_pctl": crit_pctl,
                    "coverage_warn_low_pctl": warn_cov_low_pctl,
                    "coverage_crit_low_pctl": crit_cov_low_pctl,
                },
                "breaches": breaches,
            }
            _LOG.info(
                f"regime evaluation idx={idx} alerts={alerts} drift_alerts={drift_alerts} entries={len(entries)} autotune={autotune}"
            )
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
    _EVAL_THREAD = threading.Thread(target=_loop, name="RegimeAlerts", daemon=True)
    _EVAL_THREAD.start()


def stop_regime_scheduler() -> None:
    global _RUN, _EVAL_THREAD
    if _EVAL_THREAD is None or not _EVAL_THREAD.is_alive():
        return
    _RUN = False
    _EVAL_THREAD.join(timeout=5.0)
    _EVAL_THREAD = None


def get_regime_summary(index: Optional[str] = None) -> Dict[str, Any]:
    """Return last computed regime summary.

    If index provided, returns that index's summary or {} if absent.
    If no index provided, returns mapping of all indices to summaries.
    """
    if index:
        return _LAST_SUMMARY.get(index.upper(), {})
    return dict(_LAST_SUMMARY)

__all__ = [
    "start_regime_scheduler",
    "stop_regime_scheduler",
    "get_regime_summary",
]



_REGISTRY: Any = None
_METRICS_INITIALIZED = False
_EVAL_THREAD: Optional[threading.Thread] = None
_RUN = False

_LAST_EVAL_MS: Any = None
_ALERT_COUNT: Any = None
_DRIFT_ALERT_COUNT: Any = None
_REGIME_EARLY_WARNING: Any = None
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
    global _METRICS_INITIALIZED, _REGISTRY, _LAST_EVAL_MS, _ALERT_COUNT, _DRIFT_ALERT_COUNT, _REGIME_EARLY_WARNING
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
        _DRIFT_ALERT_COUNT = Gauge(
            "g6_regime_drift_alert_count",
            "Count of horizons breaching drift thresholds",
            labelnames=["index"],
            registry=_REGISTRY,
        )
        _REGIME_EARLY_WARNING = Gauge(
            "g6_regime_early_warning_score",
            "Composite score for regime shift prediction (0-100)",
            labelnames=["index", "horizon"],
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
    def _f(env: str, default: str) -> float:
        try:
            return float(os.environ.get(env, default))
        except Exception:
            return float(default)
    coverage_min = _f("G6_REGIME_COVERAGE_MIN", "75")
    norm_p90_max = _f("G6_REGIME_NORM_ERROR_P90_MAX", "0.2")
    mae_warn = _f("G6_REGIME_MAE_DRIFT_RATIO_WARN", "1.5")
    mae_crit = _f("G6_REGIME_MAE_DRIFT_RATIO_CRIT", "2.0")
    norm_warn = _f("G6_REGIME_NORM_DRIFT_RATIO_WARN", "1.3")
    norm_crit = _f("G6_REGIME_NORM_DRIFT_RATIO_CRIT", "1.7")
    cover_drop_warn = _f("G6_REGIME_COVERAGE_DRIFT_DROP_WARN", "-10")
    cover_drop_crit = _f("G6_REGIME_COVERAGE_DRIFT_DROP_CRIT", "-20")

    for idx in _indices():
        try:
            comp = get_metric_comparison(index=idx)
            entries = comp.get("entries", []) if isinstance(comp, dict) else []
            alerts = 0
            drift_alerts = 0
            breaches: list[Dict[str, Any]] = []
            for ent in entries:
                try:
                    cov = float(ent.get("coverage_window_pct", 0.0))
                    norm_pct = ent.get("norm_error_percentiles", {}) or {}
                    p90 = float(norm_pct.get("p90", ent.get("norm_error_window", 0.0)))
                    h = int(ent.get("horizon", 0))
                    
                    # Drift metrics
                    mae_ratio = float(ent.get("mae_drift_ratio", 0.0))
                    norm_ratio = float(ent.get("norm_error_drift_ratio", 0.0))
                    cover_delta = float(ent.get("coverage_drift_delta_pct", 0.0))
                    
                    # Base regime checks
                    reasons: list[str] = []
                    if cov < coverage_min:
                        reasons.append(f"coverage<{coverage_min}")
                    if p90 > norm_p90_max:
                        reasons.append(f"norm_p90>{norm_p90_max}")
                    triggered = len(reasons) > 0
                    if triggered:
                        alerts += 1
                        
                    # Drift checks
                    drift_reasons: list[str] = []
                    if mae_ratio >= mae_crit:
                        drift_reasons.append(f"mae_ratio>={mae_crit}")
                    elif mae_ratio >= mae_warn:
                        drift_reasons.append(f"mae_ratio>={mae_warn}")
                    if norm_ratio >= norm_crit:
                        drift_reasons.append(f"norm_ratio>={norm_crit}")
                    elif norm_ratio >= norm_warn:
                        drift_reasons.append(f"norm_ratio>={norm_warn}")
                    if cover_delta <= cover_drop_crit:
                        drift_reasons.append(f"cover_drop<={cover_drop_crit}")
                    elif cover_delta <= cover_drop_warn:
                        drift_reasons.append(f"cover_drop<={cover_drop_warn}")
                    drift_triggered = len(drift_reasons) > 0
                    if drift_triggered:
                        drift_alerts += 1

                    # Phase 12: Regime Early-Warning Score
                    # Formula: (coverage_drop_rate * 0.7) + (norm_error_rise_rate * 0.3)
                    # Normalize inputs to 0-100 scale for scoring
                    # Coverage drop: -10% -> 50 score, -20% -> 100 score
                    cov_score = min(100, max(0, (-cover_delta / 20.0) * 100))
                    # Norm error rise: 1.3x -> 50 score, 1.7x -> 100 score
                    norm_score = min(100, max(0, ((norm_ratio - 1.0) / 0.7) * 100))
                    
                    early_warning_score = (cov_score * 0.7) + (norm_score * 0.3)
                    
                    if _REGIME_EARLY_WARNING is not None:
                        _REGIME_EARLY_WARNING.labels(index=idx, horizon=h).set(early_warning_score)

                    breaches.append({
                        "horizon": h,
                        "coverage_window_pct": cov,
                        "norm_error_p90": p90,
                        "triggered": triggered,
                        "reasons": reasons,
                        "mae_drift_ratio": mae_ratio,
                        "norm_error_drift_ratio": norm_ratio,
                        "coverage_drift_delta_pct": cover_delta,
                        "drift_triggered": drift_triggered,
                        "drift_reasons": drift_reasons,
                        "early_warning_score": early_warning_score,
                    })
                except Exception:
                    continue
            if _ALERT_COUNT is not None:
                _ALERT_COUNT.labels(index=idx).set(float(alerts))
            if _DRIFT_ALERT_COUNT is not None:
                _DRIFT_ALERT_COUNT.labels(index=idx).set(float(drift_alerts))
            if _LAST_EVAL_MS is not None:
                _LAST_EVAL_MS.labels(index=idx).set(time.time() * 1000.0)
            # Store last summary for status endpoint
            _LAST_SUMMARY[idx] = {
                "index": idx,
                "ts_ms": int(time.time() * 1000.0),
                "alerts": int(alerts),
                "drift_alerts": int(drift_alerts),
                "total_horizons": len(entries),
                "coverage_min": coverage_min,
                "norm_error_p90_max": norm_p90_max,
                "breaches": breaches,
            }
            _LOG.info(f"regime evaluation idx={idx} alerts={alerts} drift_alerts={drift_alerts} entries={len(entries)}")
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
