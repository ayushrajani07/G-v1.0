from __future__ import annotations
"""Universal Advisor API router."""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from typing import Optional
import time
try:
    # Prefer absolute import to avoid relative package depth issues blocking router registration
    from src.advisor.core import AdvisorContext, build_default_engine  # type: ignore
except BaseException as e:  # fallback to relative (legacy) if absolute fails
    import asyncio
    if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
        raise
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
    except (TypeError, ValueError):
        age_minutes = None
    # Update Prometheus gauge (advisor_age_minutes) if available and age computed
    try:
        if age_minutes is not None:
            from src.metrics import get_metrics_singleton  # type: ignore
            _reg = get_metrics_singleton()
            if _reg is not None and hasattr(_reg, 'advisor_age_minutes'):
                _reg.advisor_age_minutes.set(age_minutes)  # type: ignore[attr-defined]
    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        pass
    return JSONResponse({'age_minutes': age_minutes, 'generated_at': ts_iso, 'indices': idxs})
