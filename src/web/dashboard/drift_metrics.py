"""Drift Metrics & Evaluator Thread (Phase 10 P3 Optimization)

Provides Prometheus gauges for drift monitoring and a background evaluator thread.

Environment Variables:
  G6_DRIFT_ENABLE=1                  Enable drift evaluator
  G6_DRIFT_EVAL_INTERVAL_SEC=300     Evaluation interval seconds
  G6_DRIFT_INDICES=NIFTY,BANKNIFTY   Comma-separated indices to evaluate
  G6_DRIFT_BASELINE_REFRESH_DAYS=30  Days after which baseline auto-refreshes
  G6_DRIFT_CRITICAL_ALERT_REFRESH_COUNT=3  Critical feature count to trigger refresh

Relies on `src.ml.drift_monitor.DriftMonitor` for computation (severity classification included).
Gauges (per feature,index):
  g6_feature_psi
  g6_feature_ks_pvalue
  g6_feature_mean_delta
  g6_feature_var_ratio
  g6_feature_drift_severity (0=stable,1=watch,2=actionable,3=critical)

Gauges (per index):
    g6_drift_baseline_age_days
    g6_drift_critical_feature_count
    g6_drift_last_eval_ms
    g6_drift_eval_duration_ms (duration of last evaluation)
    g6_feature_drift_excluded_total (count of excluded features due to cap)
"""
from __future__ import annotations

import os, logging, threading, time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.ml.drift_monitor import create_drift_monitor_from_env

_LOG = logging.getLogger(__name__)

_REGISTRY: Any = None
_INITIALIZED = False
_THREAD: Optional[threading.Thread] = None
_RUNNING = False

_FEATURE_PSI = None
_FEATURE_KS = None
_FEATURE_MEAN_DELTA = None
_FEATURE_VAR_RATIO = None
_FEATURE_SEVERITY = None
_BASELINE_AGE = None
_CRITICAL_COUNT = None
_LAST_EVAL_MS = None
_EVAL_DURATION_MS = None
_EXCLUDED_TOTAL = None

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except Exception:
        return default

def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)

def _is_enabled() -> bool:
    return os.environ.get('G6_DRIFT_ENABLE', '0').strip() == '1'

def _init_metrics() -> bool:
    global _INITIALIZED, _REGISTRY
    global _FEATURE_PSI, _FEATURE_KS, _FEATURE_MEAN_DELTA, _FEATURE_VAR_RATIO, _FEATURE_SEVERITY
    global _BASELINE_AGE, _CRITICAL_COUNT, _LAST_EVAL_MS, _EVAL_DURATION_MS, _EXCLUDED_TOTAL
    if _INITIALIZED:
        return True
    try:
        from prometheus_client import CollectorRegistry, Gauge
        # Reuse forecast registry if available
        try:
            from .prom_metrics import get_registry as _get_forecast_registry  # type: ignore
            fr = _get_forecast_registry()
            if fr is not None:
                _REGISTRY = fr
        except Exception:
            pass
        if _REGISTRY is None:
            _REGISTRY = CollectorRegistry()
        _FEATURE_PSI = Gauge('g6_feature_psi', 'Population Stability Index', ['feature','index'], registry=_REGISTRY)
        _FEATURE_KS = Gauge('g6_feature_ks_pvalue', 'KS test p-value', ['feature','index'], registry=_REGISTRY)
        _FEATURE_MEAN_DELTA = Gauge('g6_feature_mean_delta', 'Mean delta recent - baseline', ['feature','index'], registry=_REGISTRY)
        _FEATURE_VAR_RATIO = Gauge('g6_feature_var_ratio', 'Variance ratio recent/baseline', ['feature','index'], registry=_REGISTRY)
        _FEATURE_SEVERITY = Gauge('g6_feature_drift_severity', 'Drift severity (0 stable,1 watch,2 actionable,3 critical)', ['feature','index'], registry=_REGISTRY)
        _BASELINE_AGE = Gauge('g6_drift_baseline_age_days', 'Baseline age days', ['index'], registry=_REGISTRY)
        _CRITICAL_COUNT = Gauge('g6_drift_critical_feature_count', 'Critical drift feature count', ['index'], registry=_REGISTRY)
        _LAST_EVAL_MS = Gauge('g6_drift_last_eval_ms', 'Last drift evaluation timestamp (ms since epoch)', ['index'], registry=_REGISTRY)
        _EVAL_DURATION_MS = Gauge('g6_drift_eval_duration_ms', 'Duration of last drift evaluation (ms)', ['index'], registry=_REGISTRY)
        _EXCLUDED_TOTAL = Gauge('g6_feature_drift_excluded_total', 'Number of features excluded due to cap', ['index'], registry=_REGISTRY)
        _INITIALIZED = True
        _LOG.info('Drift metrics initialized')
        return True
    except Exception as e:  # pragma: no cover
        _LOG.error(f'drift metrics init failed: {e}')
        return False

def get_registry():  # pragma: no cover
    _init_metrics()
    return _REGISTRY

_SEVERITY_MAP = {'stable':0,'watch':1,'actionable':2,'critical':3}

def _maybe_refresh_baseline(monitor, index: str, baseline: Dict[str,Any], critical_count: int) -> Dict[str,Any]:
    refresh_days = _env_int('G6_DRIFT_BASELINE_REFRESH_DAYS', 30)
    crit_refresh = _env_int('G6_DRIFT_CRITICAL_ALERT_REFRESH_COUNT', 3)
    saved_at = baseline.get('saved_at')
    age_days = 0.0
    if saved_at:
        try:
            dt = datetime.fromisoformat(saved_at.replace('Z','+00:00'))
            age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
        except Exception:
            age_days = 0.0
    # Expose age gauge
    if _BASELINE_AGE is not None:
        _BASELINE_AGE.labels(index=index).set(age_days)
    refresh_reason = None
    if age_days >= refresh_days:
        refresh_reason = f'age>=refresh_days({age_days:.1f}d >= {refresh_days}d)'
    elif critical_count >= crit_refresh:
        refresh_reason = f'critical_count>=threshold({critical_count} >= {crit_refresh})'
    if refresh_reason:
        _LOG.info(f'baseline_refresh index={index} reason={refresh_reason}')
        new_baseline = monitor.compute_feature_distributions(index, monitor.baseline_days)
        monitor.save_baseline(index, new_baseline)
        return new_baseline
    return baseline

def _evaluator_loop():
    global _RUNNING
    _LOG.info('Drift evaluator started')
    interval = _env_int('G6_DRIFT_EVAL_INTERVAL_SEC', 300)
    indices = [s.strip().upper() for s in _env_str('G6_DRIFT_INDICES','NIFTY,BANKNIFTY').split(',') if s.strip()]
    # Persist single monitor instance + baseline cache
    monitor = create_drift_monitor_from_env()
    baseline_cache: Dict[str, Dict[str,Any]] = {}
    while _RUNNING:
        loop_start = time.time()
        try:
            for idx in indices:
                t_start = time.time()
                baseline = baseline_cache.get(idx) or monitor.get_or_create_baseline(idx)
                recent = monitor.compute_feature_distributions(idx, 0)
                drift = monitor.calculate_drift_metrics(baseline, recent)
                # Apply feature cap post-scoring based on score=psi+|mean_z|
                try:
                    cap = monitor.max_features
                except Exception:
                    cap = 30
                if cap and cap > 0 and len(drift) > cap:
                    scored = []
                    fmap = getattr(monitor, 'feature_map', {}) or {}
                    for f, m in drift.items():
                        psi = float(m.get('psi', 0.0) or 0.0)
                        mean_z = float(m.get('mean_delta_zscore', m.get('mean_delta', 0.0)) or 0.0)
                        score = psi + abs(mean_z)
                        imp = 1000
                        try:
                            spec = fmap.get(f)
                            if spec is not None:
                                imp = int(getattr(spec, 'importance', 1000))
                        except Exception:
                            pass
                        scored.append((score, imp, f))
                    # Sort by: high score first, then lower importance, then feature name for determinism
                    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
                    keep = {f for _, _, f in scored[:cap]}
                    drift = {f: m for f, m in drift.items() if f in keep}
                critical_count = sum(1 for v in drift.values() if v.get('severity') == 'critical')
                if _CRITICAL_COUNT is not None:
                    _CRITICAL_COUNT.labels(index=idx).set(critical_count)
                # Baseline refresh check
                baseline = _maybe_refresh_baseline(monitor, idx, baseline, critical_count)
                baseline_cache[idx] = baseline
                # Feature cap exclusion count
                excluded = max(0, len(baseline.get('features', {})) - len(drift))
                if _EXCLUDED_TOTAL is not None:
                    _EXCLUDED_TOTAL.labels(index=idx).set(excluded)
                # Update feature gauges
                for feat, met in drift.items():
                    sev = _SEVERITY_MAP.get(met.get('severity','stable'),0)
                    if _FEATURE_PSI is not None:
                        _FEATURE_PSI.labels(feature=feat,index=idx).set(met.get('psi',0.0))
                    if _FEATURE_KS is not None:
                        _FEATURE_KS.labels(feature=feat,index=idx).set(met.get('ks_pvalue',1.0))
                    if _FEATURE_MEAN_DELTA is not None:
                        _FEATURE_MEAN_DELTA.labels(feature=feat,index=idx).set(met.get('mean_delta',0.0))
                    if _FEATURE_VAR_RATIO is not None:
                        _FEATURE_VAR_RATIO.labels(feature=feat,index=idx).set(met.get('var_ratio',1.0))
                    if _FEATURE_SEVERITY is not None:
                        _FEATURE_SEVERITY.labels(feature=feat,index=idx).set(sev)
                # Eval duration and timestamp per index
                duration_ms = (time.time() - t_start) * 1000.0
                if _EVAL_DURATION_MS is not None:
                    _EVAL_DURATION_MS.labels(index=idx).set(duration_ms)
                if _LAST_EVAL_MS is not None:
                    _LAST_EVAL_MS.labels(index=idx).set(time.time()*1000.0)
                _LOG.debug(f'drift_evaluated index={idx} features={len(drift)} critical={critical_count} duration_ms={duration_ms:.2f}')
        except Exception as e:
            _LOG.error(f'drift evaluation error: {e}')
        elapsed = time.time() - loop_start
        sleep_for = max(5.0, interval - elapsed)
        time.sleep(sleep_for)
    _LOG.info('Drift evaluator stopped')

def start_drift_evaluator():
    global _THREAD, _RUNNING
    if not _is_enabled():
        _LOG.info('Drift monitoring disabled (G6_DRIFT_ENABLE!=1)')
        return
    _init_metrics()
    if _THREAD and _THREAD.is_alive():
        return
    _RUNNING = True
    _THREAD = threading.Thread(target=_evaluator_loop, name='DriftEvaluator', daemon=True)
    _THREAD.start()
    _LOG.info('Drift evaluator thread launched')

def stop_drift_evaluator():  # pragma: no cover
    global _RUNNING, _THREAD
    _RUNNING = False
    if _THREAD:
        _THREAD.join(timeout=5.0)
        _THREAD = None

__all__ = ['start_drift_evaluator','stop_drift_evaluator','get_registry']