from __future__ import annotations
"""Universal Advisor API router."""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from typing import Optional
import time
try:
    # Prefer absolute import to avoid relative package depth issues blocking router registration
    from src.advisor.core import AdvisorContext, build_default_engine  # type: ignore
except (ImportError, ModuleNotFoundError):  # fallback to relative (legacy) if absolute fails
    from ....advisor.core import AdvisorContext, build_default_engine  # type: ignore

router = APIRouter()

@router.get("/api/ml/universal_advisor")
async def api_ml_universal_advisor(
    indices: str = Query("NIFTY", description="Comma-separated indices"),
    horizons: str = Query("60", description="Comma-separated horizons (unused v0)"),
    windows: str = Query("60,120", description="Comma-separated windows for ANN"),
    use_prometheus: bool = Query(False, description="Query Prometheus instead of scraping exporters"),
    prometheus: Optional[str] = Query(None, description="Prometheus base url e.g., http://127.0.0.1:9090"),
    ann_ports: str = Query("9308,9309,9310", description="Exporter ports for ANN scrape fallback"),
    detail: bool = Query(True, description="Include full metrics evidence"),
) -> JSONResponse:
    idxs = [s.strip().upper() for s in indices.split(',') if s.strip()]
    hs = [int(x) for x in horizons.split(',') if x.strip()]
    ws = [int(x) for x in windows.split(',') if x.strip()]
    params = {
        'prometheus': (prometheus if use_prometheus else None),
        'ann_ports': ann_ports,
        # Path plugin defaults
        'path_horizon': 60,
        'path_window_minutes': 180,
        'path_expiry_tag': 'this_month',
        'path_offset': '0',
        'path_bucket_ms': 60000,
    }
    ctx = AdvisorContext(indices=idxs, horizons=hs, windows=ws, now=time.time(), params=params)
    engine = build_default_engine(ctx)
    report = engine.run(ctx)
    if not detail:
        # Reduce payload: keep summary and flags
        report = {k: report[k] for k in ('generated_at','summary','flags')}
    return JSONResponse(report)

@router.get("/api/ml/universal_advisor/health")
async def api_ml_universal_advisor_health(
    indices: str = Query("NIFTY", description="Comma-separated indices"),
) -> JSONResponse:
    """Lightweight health probe for Infinity stat panels.

    Returns a minimal payload: generated_at, indices, counts, and overall level.
    """
    idxs = [s.strip().upper() for s in indices.split(',') if s.strip()]
    ctx = AdvisorContext(indices=idxs, horizons=[60], windows=[60,120], now=time.time(), params={})
    engine = build_default_engine(ctx)
    report = engine.run(ctx)
    summary = report.get('summary', {})
    per_index = summary.get('per_index', {})
    worst = summary.get('overall_level', 'ok')
    return JSONResponse({
        'generated_at': report.get('generated_at'),
        'indices': idxs,
        'overall_level': worst,
        'per_index': per_index,
        'counts': {
            'findings': len(report.get('findings', []) or []),
            'remedies': len(report.get('remedies', []) or []),
        }
    })

@router.get("/api/ml/universal_advisor/generated_at_age_minutes")
async def api_ml_universal_advisor_generated_at_age_minutes(
    indices: str = Query("NIFTY", description="Comma-separated indices (first used for timestamp)"),
) -> JSONResponse:
    """Return numeric age (minutes) since the advisor report was generated.

    Designed specifically for a Grafana Stat panel via Infinity datasource.
    We compute age using the same health context (single engine run) to avoid
    divergence across endpoints.
    """
    idxs = [s.strip().upper() for s in indices.split(',') if s.strip()]
    ctx = AdvisorContext(indices=idxs, horizons=[60], windows=[60,120], now=time.time(), params={})
    engine = build_default_engine(ctx)
    report = engine.run(ctx)
    ts_iso = report.get('generated_at')
    age_minutes: float | None = None
    try:
        if isinstance(ts_iso, str):
            # Expect ISO8601 Z format; parse leniently
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(ts_iso.replace('Z','+00:00'))
            age_minutes = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except (ValueError, TypeError, AttributeError):
        # Invalid timestamp format, type mismatch, or string method failure
        age_minutes = None
    # Update Prometheus gauge (advisor_age_minutes) if available and age computed
    try:
        if age_minutes is not None:
            from src.metrics import get_metrics_singleton  # type: ignore
            _reg = get_metrics_singleton()
            if _reg is not None and hasattr(_reg, 'advisor_age_minutes'):
                _reg.advisor_age_minutes.set(age_minutes)  # type: ignore[attr-defined]
    except (ImportError, AttributeError, TypeError):
        # Import failure, missing attribute, or type error - skip metrics update
        pass
    return JSONResponse({'age_minutes': age_minutes, 'generated_at': ts_iso, 'indices': idxs})

# ---------------- Drift Advice Extension (Phase 10) ----------------
def _env_float(name: str, default: float) -> float:
    import os
    try:
        return float(os.environ.get(name, str(default)).strip())
    except Exception:
        return default

_THRESHOLDS = {
    'psi_warn': _env_float('G6_DRIFT_PSI_WARN', 0.25),
    'psi_crit': _env_float('G6_DRIFT_PSI_CRIT', 0.40),
    'ks_warn': _env_float('G6_DRIFT_KS_WARN', 0.01),
    'ks_crit': _env_float('G6_DRIFT_KS_CRIT', 0.001),
    'mean_z_warn': _env_float('G6_DRIFT_MEAN_Z_WARN', 2.0),
    'mean_z_crit': _env_float('G6_DRIFT_MEAN_Z_CRIT', 3.0),
    'var_ratio_warn_high': _env_float('G6_DRIFT_VAR_RATIO_WARN_HIGH', 1.5),
    'var_ratio_warn_low': _env_float('G6_DRIFT_VAR_RATIO_WARN_LOW', 0.67),
    'var_ratio_crit_high': _env_float('G6_DRIFT_VAR_RATIO_CRIT_HIGH', 2.0),
    'var_ratio_crit_low': _env_float('G6_DRIFT_VAR_RATIO_CRIT_LOW', 0.5),
}

def _classify(rec: dict) -> tuple[str, list[str]]:
    psi = rec.get('psi', 0.0)
    ks = rec.get('ks_pvalue', 1.0)
    mean_delta = abs(rec.get('mean_delta', 0.0))
    var_ratio = rec.get('var_ratio', 1.0)
    ratio = var_ratio if isinstance(var_ratio,(int,float)) and var_ratio > 0 else 1.0
    t = _THRESHOLDS
    severity = 'stable'
    actions: list[str] = []
    warn_conditions = (
        (psi >= t['psi_warn']) or (ks <= t['ks_warn']) or (mean_delta >= t['mean_z_warn']) or (ratio >= t['var_ratio_warn_high']) or (ratio <= t['var_ratio_warn_low'])
    )
    crit_conditions = (
        (psi >= t['psi_crit']) or (ks <= t['ks_crit']) or (mean_delta >= t['mean_z_crit']) or (ratio >= t['var_ratio_crit_high']) or (ratio <= t['var_ratio_crit_low'])
    )
    if crit_conditions:
        severity = 'critical'
        actions = ['raise_alert', 'consider_baseline_refresh', 'evaluate_retraining']
    elif warn_conditions and ((psi >= t['psi_warn'] and (ks <= t['ks_warn'] or mean_delta >= t['mean_z_warn'])) or (mean_delta >= t['mean_z_warn'] and psi >= t['psi_warn'])):
        severity = 'actionable'
        actions = ['investigate_feature_pipeline', 'validate_recent_data']
    elif warn_conditions:
        severity = 'watch'
        actions = ['monitor_next_cycles']
    return severity, actions

@router.get('/api/ml/universal_advisor/drift_advice')
async def api_ml_universal_advisor_drift_advice(
    index: str = Query('NIFTY', description='Index symbol'),
    detail: bool = Query(True, description='Include per-feature breakdown'),
):
    """Return drift classification & recommended actions based on current drift gauges.

    Uses thresholds from environment variables (G6_DRIFT_*). Falls back to defaults if unset.
    """
    # Obtain drift metric snapshot from prom_metrics (placeholder tolerant)
    try:
            from src.web.dashboard.prom_metrics import get_feature_drift_snapshot  # type: ignore
            snapshot = get_feature_drift_snapshot(index.upper()) or []
    except Exception:
        snapshot = []
    entries = []
    counts = {'stable':0,'watch':0,'actionable':0,'critical':0}
    severity_map = {0:'stable',1:'watch',2:'actionable',3:'critical'}
    for rec in snapshot:
        raw_sev = rec.get('severity')
        sev_label: str
        if isinstance(raw_sev,(int,float)) and raw_sev in severity_map:
            sev_label = severity_map[int(raw_sev)]
            # actions derived from severity directly
            if sev_label == 'critical':
                acts = ['raise_alert','consider_baseline_refresh','evaluate_retraining']
            elif sev_label == 'actionable':
                acts = ['investigate_feature_pipeline','validate_recent_data']
            elif sev_label == 'watch':
                acts = ['monitor_next_cycles']
            else:
                acts = []
        else:
            # fallback to classification if severity gauge missing
            sev_label, acts = _classify(rec)
        counts[sev_label] += 1
        if detail:
            entries.append({
                'feature': rec.get('feature'),
                'psi': rec.get('psi'),
                'ks_pvalue': rec.get('ks_pvalue'),
                'mean_delta': rec.get('mean_delta'),
                'var_ratio': rec.get('var_ratio'),
                'severity': sev_label,
                'actions': acts,
            })
    recommend_retrain = counts['critical'] >= 2 or counts['actionable'] >= 5
    result = {
        'index': index.upper(),
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'thresholds': _THRESHOLDS,
        'summary': counts,
        'recommend_retrain': recommend_retrain,
    }
    if detail:
        result['features'] = entries
    return JSONResponse(result)
