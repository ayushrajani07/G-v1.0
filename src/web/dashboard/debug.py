"""Debug endpoints for Web API.

MEDIUM_IMPACT_OPTIMIZATION (Opportunity 5):
Extracted DEBUG endpoints from app.py to separate module for cleaner production code.
These endpoints are only enabled when G6_DASHBOARD_DEBUG=1 environment variable is set.

Benefits:
- Production app.py is cleaner (no debug clutter)
- Debug code can evolve independently
- Easier security review (debug endpoints isolated)
- Clearer separation of concerns
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from src.web.dashboard.metrics_cache import MetricsCache

# Expected core metrics for validation
_EXPECTED_CORE = [
    'g6_uptime_seconds', 'g6_collection_cycle_time_seconds', 'g6_options_processed_per_minute',
    'g6_collection_success_rate_percent', 'g6_api_success_rate_percent', 'g6_cpu_usage_percent',
    'g6_memory_usage_mb', 'g6_index_cycle_attempts', 'g6_index_cycle_success_percent',
    'g6_index_options_processed', 'g6_index_options_processed_total'
]

# Create debug router that will be conditionally included in main app
debug_router = APIRouter(prefix="/debug", tags=["debug"])

# Cache will be set by app.py after initialization
_cache: MetricsCache | None = None


def set_cache(cache: MetricsCache) -> None:
    """Set the metrics cache instance for debug endpoints."""
    global _cache
    _cache = cache


@debug_router.get('/metrics')
async def debug_metric_names() -> dict[str, Any]:
    """Return all metric names with sample counts."""
    if _cache is None:
        raise HTTPException(status_code=503, detail='cache not initialized')
    snap = _cache.snapshot()
    if not snap:
        raise HTTPException(status_code=503, detail='no snapshot yet')
    data = {name: len(samples) for name, samples in sorted(snap.raw.items())}
    return {'ts': snap.ts, 'age_seconds': snap.age_seconds, 'count': len(data), 'metrics': data}


@debug_router.get('/missing')
async def debug_missing() -> dict[str, Any]:
    """Show which core metrics are missing from current snapshot."""
    if _cache is None:
        raise HTTPException(status_code=503, detail='cache not initialized')
    snap = _cache.snapshot()
    if not snap:
        raise HTTPException(status_code=503, detail='no snapshot yet')
    present = set(snap.raw.keys())
    missing = [m for m in _EXPECTED_CORE if m not in present]
    return {'missing_core_metrics': missing, 'present_core': list(present & set(_EXPECTED_CORE))}


@debug_router.get('/indices')
async def debug_indices() -> dict[str, Any]:
    """Compute index statistics on-demand from raw metrics.
    
    Shows per-index options processed (legs) and success rates.
    Computes directly from raw metrics without caching.
    """
    if _cache is None:
        raise HTTPException(status_code=503, detail='cache not initialized')
    snap = _cache.snapshot()
    if not snap:
        raise HTTPException(status_code=503, detail='no snapshot yet')
    
    # Compute minimal index stats from raw metrics
    idx_opts = snap.raw.get('g6_index_options_processed', [])
    idx_success = snap.raw.get('g6_index_cycle_success_percent', [])
    
    rows = []
    for sample in idx_opts:
        index_name = sample.labels.get('index', '?')
        legs = int(sample.value) if sample.value is not None else 0
        
        # Find matching success rate
        succ = None
        for s in idx_success:
            if s.labels.get('index') == index_name:
                succ = s.value
                break
        
        rows.append({
            'index': index_name,
            'legs': legs,
            'success': succ,
        })
    
    return {'rows': rows, 'count': len(rows)}


@debug_router.get('/raw/{metric_name}')
async def debug_raw_metric(metric_name: str) -> PlainTextResponse:
    """Return raw metric samples in Prometheus text format.
    
    Args:
        metric_name: The name of the metric to retrieve
        
    Returns:
        Plain text response with metric samples in Prometheus format
    """
    if _cache is None:
        raise HTTPException(status_code=503, detail='cache not initialized')
    snap = _cache.snapshot()
    if not snap:
        raise HTTPException(status_code=503, detail='no snapshot yet')
    samples = snap.raw.get(metric_name)
    if not samples:
        raise HTTPException(status_code=404, detail=f'metric {metric_name} not found')
    out = []
    for s in samples:
        if s.labels:
            label_str = ','.join(f'{k}="{v}"' for k, v in s.labels.items())
            out.append(f'{metric_name}{{{label_str}}} {s.value}')
        else:
            out.append(f'{metric_name} {s.value}')
    return PlainTextResponse('\n'.join(out))
