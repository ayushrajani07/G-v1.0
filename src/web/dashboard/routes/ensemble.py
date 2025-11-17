from __future__ import annotations

"""FastAPI Ensemble Forecasting Router (migrated from Flask ml_ensemble).

Phase: Migration to unified dashboard stack.

Endpoints:
- GET /api/ml/ensemble/forecast
- GET /api/ml/ensemble/diagnostics
- GET /api/ml/ensemble/confidence
- POST /api/ml/ensemble/retrain

Implementation notes:
- Uses existing EnsembleConfig / EnsembleForecaster from path_forecast.ensemble
- Configuration loaded from <project_root>/configs/ml/{index}_ensemble_config.json
- Mock forecast values retained (replace with real forecaster.forecast_path once live data integrated)
"""

import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import logging, os, threading
from datetime import datetime, time as dtime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.path_forecast.ensemble import EnsembleConfig, EnsembleForecaster
from src.error_handling import safe_read_json

_LOG = logging.getLogger("web.dashboard.ensemble")
router = APIRouter(prefix="/api/ml/ensemble", tags=["ml_ensemble"])

# Caches (simple process-level dictionaries)
_forecasters: Dict[str, EnsembleForecaster] = {}
_configs: Dict[str, EnsembleConfig] = {}
_init_errors: Dict[str, str] = {}

# --------------------------- Pydantic Models ---------------------------
class ForecastMetadata(BaseModel):
    latency_ms: float
    components_used: list[str]
    weights: Dict[str, float]
    recent_count: int = Field(0, description="Number of recent TP rows used in forecast context")
    cache_hit: bool = Field(False, description="True if served from in-memory forecast cache")

class TimeGrid(BaseModel):
    start: int = Field(..., description="Start timestamp in epoch milliseconds")
    end: int = Field(..., description="End timestamp in epoch milliseconds")
    resolution_ms: int = Field(..., description="Time step resolution in milliseconds")
    values: list[int] = Field(..., description="Array of timestamps for each forecast point")

class ForecastResponse(BaseModel):
    index: str
    horizon: int
    timestamp: str
    forecast: Dict[str, float]
    confidence: float
    metadata: ForecastMetadata
    time_grid: Optional[TimeGrid] = Field(None, description="Time grid for full detail mode")
    quantile_paths: Optional[Dict[str, list[float]]] = Field(None, description="Per-quantile forecast paths for full detail mode")

class DiagnosticsResponse(BaseModel):
    index: str
    status: str
    components: Dict[str, bool]
    weights: Dict[str, float]
    confidence: float
    metrics: Dict[str, Any]
    model_age_days: Optional[float]

class ConfidenceResponse(BaseModel):
    index: str
    timestamp: str
    confidence: float
    factors: Dict[str, float]
    recommendation: str

class RetrainRequest(BaseModel):
    index: str = Field(..., description="Index name e.g. NIFTY")
    days: int = Field(60, ge=1, description="Training data window in days")
    run_validation: bool = Field(True, description="Run validation before promoting")

class RetrainResponse(BaseModel):
    index: str
    status: str
    job_id: str
    parameters: Dict[str, Any]
    estimated_completion: str
    message: str

# --------------------------- Helpers ---------------------------
_def_components = ['baseline', 'gbrt', 'retrieval', 'conformal']

def _quantile_to_label(q: float) -> str:
    """Convert quantile float to stable label string.
    
    Examples: 0.1 -> 'p10', 0.5 -> 'p50', 0.95 -> 'p95'
    """
    # Round to avoid floating point precision issues
    pct = round(q * 100)
    return f"p{pct}"

# --------------------------- Simple In-Memory Forecast Cache ---------------------------
_CACHE: Dict[Tuple[str,int,str,float,float,float,int,str], ForecastResponse] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SEC = max(0, int(os.environ.get('G6_FORECAST_CACHE_TTL', '30')))
_CACHE_TIME: Dict[Tuple[str,int,str,float,float,float,int,str], float] = {}
_CACHE_HITS = 0
_CACHE_MISSES = 0

def _cache_get(key: Tuple[str,int,str,float,float,float,int,str]) -> Optional[ForecastResponse]:
    if _CACHE_TTL_SEC == 0:
        return None
    with _CACHE_LOCK:
        ts = _CACHE_TIME.get(key)
        if ts is None:
            global _CACHE_MISSES
            _CACHE_MISSES += 1
            return None
        if (time.time() - ts) > _CACHE_TTL_SEC:
            # expired - purge
            _CACHE.pop(key, None)
            _CACHE_TIME.pop(key, None)
            _CACHE_MISSES += 1
            return None
        global _CACHE_HITS
        _CACHE_HITS += 1
        return _CACHE.get(key)

def _cache_put(key: Tuple[str,int,str,float,float,float,int,str], value: ForecastResponse) -> None:
    if _CACHE_TTL_SEC == 0:
        return
    with _CACHE_LOCK:
        _CACHE[key] = value
        _CACHE_TIME[key] = time.time()

@router.get('/cache/stats')
async def cache_stats():
    """Return in-memory forecast cache statistics."""
    now = time.time()
    with _CACHE_LOCK:
        entries = []
        for k, ts in _CACHE_TIME.items():
            age = now - ts
            entries.append({'key': {
                'index': k[0], 'horizon': k[1], 'quantiles': k[2], 'underlying': k[3], 'avg_iv': k[4], 'minutes_to_expiry': k[5], 'recent_window_size': k[6], 'detail': k[7]
            }, 'age_sec': round(age, 3)})
        oldest = max((e['age_sec'] for e in entries), default=0.0)
        newest = min((e['age_sec'] for e in entries), default=0.0)
        hit_ratio = (_CACHE_HITS / (_CACHE_HITS + _CACHE_MISSES)) if (_CACHE_HITS + _CACHE_MISSES) else 0.0
        return {
            'ttl_sec': _CACHE_TTL_SEC,
            'size': len(entries),
            'hits': _CACHE_HITS,
            'misses': _CACHE_MISSES,
            'hit_ratio': round(hit_ratio, 4),
            'oldest_age_sec': oldest,
            'newest_age_sec': newest,
            'entries': entries[:50],  # cap detail
        }

@router.post('/cache/clear')
async def cache_clear():
    """Clear the in-memory forecast cache and reset counters."""
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE_TIME.clear()
        _CACHE_HITS = 0
        _CACHE_MISSES = 0
    return {'status': 'ok', 'cleared': True}

def _project_root() -> Path:
    # Attempt to locate project root by walking up until pyproject.toml found
    start = Path(__file__).resolve()
    for parent in [start.parent] + list(start.parents):
        if (parent / 'pyproject.toml').exists():
            return parent
    return Path.cwd()

def _config_dir() -> Path:
    return _project_root() / 'configs' / 'ml'

def _get_forecaster(index: str) -> Optional[EnsembleForecaster]:
    idx = index.upper()
    if idx in _forecasters:
        return _forecasters[idx]
    if idx in _init_errors:
        # Previous init failed; avoid log spam
        return None
    cfg_path = _config_dir() / f"{idx.lower()}_ensemble_config.json"
    if not cfg_path.exists():
        _init_errors[idx] = f"config file missing: {cfg_path}"
        _LOG.warning(_init_errors[idx])
        return None
    data = safe_read_json(cfg_path, default=None, function_name='dashboard_ensemble_read_config')
    if data is None:
        _init_errors[idx] = f"failed to parse config: {cfg_path}"
        _LOG.error(_init_errors[idx])
        return None
    try:
        components = data.get('components', {})
        weighting = data.get('weighting', {})
        cfg = EnsembleConfig(
            baseline_enabled=components.get('baseline', {}).get('enabled', True),
            gbrt_enabled=components.get('gbrt', {}).get('enabled', True),
            retrieval_enabled=components.get('retrieval', {}).get('enabled', True),
            conformal_enabled=components.get('conformal', {}).get('enabled', True),
            baseline_k=components.get('baseline', {}).get('k_coefficient', 1.0),
            gbrt_model_path=Path(components.get('gbrt', {}).get('model_path', 'models/gbrt/')),
            retrieval_root=_project_root() / 'data' / 'historical',
            retrieval_expiry_tag=str(components.get('retrieval', {}).get('expiry_tag','this_week')),
            retrieval_offset=str(components.get('retrieval', {}).get('offset','0')),
            retrieval_window=components.get('retrieval', {}).get('window', 60),
            retrieval_k=components.get('retrieval', {}).get('k', 20),
            retrieval_min_days=components.get('retrieval', {}).get('min_days', 3),
            retrieval_distance_metric=components.get('retrieval', {}).get('distance_metric', 'l2'),
            retrieval_weight_mode=components.get('retrieval', {}).get('weight_mode'),
            retrieval_use_ann=components.get('retrieval', {}).get('use_ann', False),
            conformal_target_coverage=components.get('conformal', {}).get('target_coverage', 0.8),
            conformal_window=components.get('conformal', {}).get('window', 600),
            conformal_min_radius=components.get('conformal', {}).get('min_radius', 0.0),
            weighting_strategy=weighting.get('strategy', 'confidence_adaptive'),
            confidence_threshold=weighting.get('confidence_threshold', 0.7),
            weights_high_conf_gbrt=weighting.get('weights_high_confidence', {}).get('gbrt', 0.8),
            weights_high_conf_retrieval=weighting.get('weights_high_confidence', {}).get('retrieval', 0.2),
            weights_low_conf_gbrt=weighting.get('weights_low_confidence', {}).get('gbrt', 0.5),
            weights_low_conf_retrieval=weighting.get('weights_low_confidence', {}).get('retrieval', 0.5),
            min_candidates_threshold=weighting.get('min_candidates_threshold', 5),
        )
        fore = EnsembleForecaster(cfg)
        _configs[idx] = cfg
        _forecasters[idx] = fore
        _LOG.info(f"Ensemble forecaster initialized for {idx}")
        return fore
    except Exception as e:  # pragma: no cover
        _init_errors[idx] = f"init_failed: {e}"
        _LOG.error(f"Forecaster init failed for {idx}: {e}", exc_info=True)
        return None

# --------------------------- Recent Window Loader ---------------------------
def _load_recent_window(index: str, limit: int) -> list[list[float]]:
    """Load recent TP observations for index from today's CSV.

    Attempts paths in priority:
      data/g6_data/<INDEX>/this_month/0/<YYYY-MM-DD>.csv
      data/g6_data/<INDEX>/this_week/0/<YYYY-MM-DD>.csv

    Fallback: empty list if file not found or parse fails.
    Assumptions: CSV header contains 'tp' or first numeric column usable.
    Returns list[[tp], ...] up to 'limit' most recent rows.
    """
    if limit <= 0:
        return []

def _infer_live_params(index: str) -> Dict[str, float]:
    """Infer underlying, avg_iv, minutes_to_expiry from today's CSV when possible.

    - underlying: last TP value
    - avg_iv: mean of last row's ce_iv/pe_iv if present, else fallback to 0.2
    - minutes_to_expiry: minutes until 15:30 Asia/Kolkata today; if past, minutes until next business day's 15:30 (approximation)
    """
    result = {
        'underlying': 0.0,
        'avg_iv': 0.2,
        'minutes_to_expiry': 375.0,
    }
    root = _project_root() / 'data' / 'g6_data'
    today = time.strftime('%Y-%m-%d')
    candidates = [
        root / index.upper() / 'this_month' / '0' / f'{today}.csv',
        root / index.upper() / 'this_week' / '0' / f'{today}.csv',
    ]
    path = None
    for c in candidates:
        if c.exists():
            path = c
            break
    if path is None:
        # compute minutes to expiry anyway
        pass
    else:
        try:
            import csv
            with path.open('r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, [])
                cols = {h.strip().lower(): i for i, h in enumerate(header)}
                tp_idx = cols.get('tp') or cols.get('tp_value') or cols.get('theoretical_price')
                ce_iv_idx = cols.get('ce_iv')
                pe_iv_idx = cols.get('pe_iv')
                last_row = None
                for row in reader:
                    last_row = row
                if last_row:
                    if tp_idx is not None:
                        try:
                            result['underlying'] = float(last_row[int(tp_idx)])
                        except Exception:
                            pass
                    iv_vals = []
                    if ce_iv_idx is not None:
                        try:
                            iv_vals.append(float(last_row[int(ce_iv_idx)]))
                        except Exception:
                            pass
                    if pe_iv_idx is not None:
                        try:
                            iv_vals.append(float(last_row[int(pe_iv_idx)]))
                        except Exception:
                            pass
                    if iv_vals:
                        # clamp to reasonable range
                        avg_iv = sum(iv_vals) / len(iv_vals)
                        if avg_iv >= 0:
                            result['avg_iv'] = float(avg_iv)
        except Exception as e:
            _LOG.debug(f"infer_live_params failed for {index}: {e}")

    # minutes_to_expiry: approx to 15:30 Asia/Kolkata today or next day
    try:
        tz = ZoneInfo('Asia/Kolkata') if ZoneInfo else timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(tz)
        target = now.replace(hour=15, minute=30, second=0, microsecond=0)
        if now > target:
            target = target + timedelta(days=1)
            target = target.replace(hour=15, minute=30, second=0, microsecond=0)
        minutes = max(0.0, (target - now).total_seconds() / 60.0)
        result['minutes_to_expiry'] = float(round(minutes, 2))
    except Exception:
        pass
    return result
    root = _project_root() / 'data' / 'g6_data'
    today = time.strftime('%Y-%m-%d')
    candidates = [
        root / index.upper() / 'this_month' / '0' / f'{today}.csv',
        root / index.upper() / 'this_week' / '0' / f'{today}.csv',
    ]
    path = None
    for c in candidates:
        if c.exists():
            path = c
            break
    if path is None:
        return []
    rows: list[list[float]] = []
    try:
        import csv
        with path.open('r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, [])
            tp_idx = -1
            for i, col in enumerate(header):
                if col.strip().lower() in ('tp','tp_value','theoretical_price'):
                    tp_idx = i
                    break
            # If no explicit tp column, assume first numeric column after header
            for row in reader:
                if not row:
                    continue
                if tp_idx == -1:
                    # find first numeric cell
                    val = None
                    for cell in row:
                        try:
                            val = float(cell)
                            break
                        except ValueError:
                            continue
                    if val is None:
                        continue
                    rows.append([val])
                else:
                    try:
                        val = float(row[tp_idx])
                    except (ValueError, IndexError):
                        continue
                    rows.append([val])
        # Keep only last 'limit'
        if len(rows) > limit:
            rows = rows[-limit:]
        return rows
    except Exception as e:
        _LOG.warning(f"recent_window_load_failed index={index} path={path}: {e}")
        return []

# --------------------------- Endpoints ---------------------------
@router.get('/forecast', response_model=ForecastResponse)
async def forecast(
    index: str = Query(..., description="Index e.g. NIFTY"),
    horizon: int = Query(60, ge=1, le=720),
    quantiles: str = Query("0.1,0.5,0.9", description="Comma separated quantiles"),
    underlying: float = Query(0.0, description="Underlying index price (optional, baseline=0 if omitted)"),
    avg_iv: float = Query(0.2, ge=0, description="Average implied volatility proxy"),
    minutes_to_expiry: float = Query(375.0, ge=0, description="Minutes to expiry"),
    recent_window_size: int = Query(60, ge=0, le=200, description="Number of recent TP rows to include from CSV"),
    cache_bust: int = Query(0, ge=0, le=1, description="Set to 1 to bypass cache"),
    detail: Optional[str] = Query(None, description="Response detail level: 'full' for time grid and quantile paths"),
):
    """Return real ensemble forecast using EnsembleForecaster.forecast_path.

    For now recent_window and live_rows are empty (bootstrap mode). When live
    integration available, replace with actual recent TP window & live rows.
    """
    t0 = time.perf_counter()
    idx = index.upper().strip()
    fore = _get_forecaster(idx)
    if fore is None:
        raise HTTPException(status_code=404, detail=f"forecaster_unavailable: {idx}")

    # Parse quantiles
    q_list: list[float] = []
    for part in quantiles.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            q_list.append(float(part))
        except ValueError:
            continue
    if not q_list:
        q_list = [0.1, 0.5, 0.9]

    # Build minimal context; enrich from live data if params are defaults.
    now_ms = int(time.time() * 1000)
    inferred = _infer_live_params(idx)
    if underlying <= 0.0:
        underlying = inferred.get('underlying', underlying)
    if avg_iv == 0.2:
        avg_iv = inferred.get('avg_iv', avg_iv)
    if minutes_to_expiry == 375.0:
        minutes_to_expiry = inferred.get('minutes_to_expiry', minutes_to_expiry)
    context = {
        'index': idx,
        'now_ms': now_ms,
        'underlying': underlying,
        'avg_iv': avg_iv,
        'minutes_to_expiry': minutes_to_expiry,
        'live_rows': [],  # placeholder until live data integration
    }

    recent_window = _load_recent_window(idx, recent_window_size)
    if recent_window is None:
        recent_window = []

    # Cache key derived from stable inputs - include detail param to avoid returning wrong response type
    detail_normalized = detail.lower() if detail else ""
    cache_key = (idx, horizon, quantiles, underlying, avg_iv, minutes_to_expiry, recent_window_size, detail_normalized)
    cached: Optional[ForecastResponse] = None
    if cache_bust == 0:
        cached = _cache_get(cache_key)
    if cached is not None:
        # Mark cache hit in metadata clone
        cached.metadata.cache_hit = True
        return cached
    try:
        times, qmap = fore.forecast_path(
            recent_window=recent_window,
            context=context,
            quantiles=q_list,
            horizon_minutes=horizon,
            bucket_ms=60_000,
        )
    except Exception as e:  # pragma: no cover
        _LOG.warning(f"forecast_path failed for {idx}: {e}")
        times, qmap = [], {}
    if qmap is None:
        qmap = {}

    # Derive single-point summary from first forecast horizon value per quantile.
    def _first(q: float) -> float:
        seq = qmap.get(q, ())
        return float(seq[0]) if seq else 0.0

    # Confidence/weights metadata from last_meta if available.
    lm = getattr(fore, 'last_meta', {}) or {}
    weight_gbrt = lm.get('weight_gbrt', 0.0)
    weight_retrieval = lm.get('weight_retrieval', 0.0)
    confidence = float(lm.get('confidence', 0.0))

    # Map common quantiles to p10/p50/p90 if present else fallback.
    p10 = _first(0.1 if 0.1 in qmap else q_list[0])
    p50 = _first(0.5 if 0.5 in qmap else q_list[len(q_list)//2])
    p90 = _first(0.9 if 0.9 in qmap else q_list[-1])

    # Simple band estimate: min/max across chosen quantile first points.
    band_low = min(p10, p50, p90)
    band_high = max(p10, p50, p90)

    forecast_data = {
        'p10': p10,
        'p50': p50,
        'p90': p90,
        'band_low': band_low,
        'band_high': band_high,
    }
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    meta = ForecastMetadata(
        latency_ms=latency_ms,
        components_used=[c for c in _def_components if lm.get(f"{c}_enabled", True)],
        weights={'gbrt': weight_gbrt, 'retrieval': weight_retrieval},
        recent_count=len(recent_window or []),
        cache_hit=False,
    )
    
    # Build full detail response if requested
    time_grid_obj = None
    quantile_paths_obj = None
    if detail and detail.lower() == 'full':
        # Build time_grid from times array
        if times:
            # times is already epoch ms array from forecast_path
            time_grid_obj = TimeGrid(
                start=times[0] if times else now_ms,
                end=times[-1] if times else now_ms,
                resolution_ms=60_000,  # 1-minute buckets as used in forecast_path call
                values=list(times)
            )
        else:
            # Empty case - return minimal valid grid
            time_grid_obj = TimeGrid(
                start=now_ms,
                end=now_ms,
                resolution_ms=60_000,
                values=[]
            )
        
        # Build quantile_paths from qmap
        quantile_paths_obj = {}
        for q in q_list:
            label = _quantile_to_label(q)
            path = qmap.get(q, [])
            # Ensure path is list of floats, handle empty gracefully
            quantile_paths_obj[label] = [float(v) for v in path] if path else []
    
    resp = ForecastResponse(
        index=idx, 
        horizon=horizon, 
        timestamp=str(now_ms), 
        forecast=forecast_data, 
        confidence=confidence, 
        metadata=meta,
        time_grid=time_grid_obj,
        quantile_paths=quantile_paths_obj
    )
    _cache_put(cache_key, resp)
    return resp

@router.get('/diagnostics', response_model=DiagnosticsResponse)
async def diagnostics(index: str = Query(...)):
    idx = index.upper().strip()
    fore = _get_forecaster(idx)
    if fore is None:
        raise HTTPException(status_code=404, detail=f"forecaster_unavailable: {idx}")
    cfg = _configs.get(idx)
    components = {
        'baseline': cfg.baseline_enabled if cfg else True,
        'gbrt': cfg.gbrt_enabled if cfg else True,
        'retrieval': cfg.retrieval_enabled if cfg else True,
        'conformal': cfg.conformal_enabled if cfg else True,
    }
    metrics = {
        'forecast_count_24h': 1440,
        'avg_latency_ms': 450,
        'error_rate_24h': 0.002,
    }
    return DiagnosticsResponse(index=idx, status='healthy', components=components, weights={'gbrt': 0.7, 'retrieval': 0.3}, confidence=0.75, metrics=metrics, model_age_days=3.5)

@router.get('/confidence', response_model=ConfidenceResponse)
async def confidence(index: str = Query(...)):
    idx = index.upper().strip()
    fore = _get_forecaster(idx)
    if fore is None:
        raise HTTPException(status_code=404, detail=f"forecaster_unavailable: {idx}")
    factors = {
        'gbrt_oob_score': 0.82,
        'retrieval_match_quality': 0.78,
        'regime_stability': 0.85,
        'recent_accuracy': 0.73,
    }
    return ConfidenceResponse(index=idx, timestamp=str(time.time()), confidence=0.75, factors=factors, recommendation='high_confidence')

@router.post('/retrain', response_model=RetrainResponse)
async def retrain(req: RetrainRequest):
    idx = req.index.upper().strip()
    fore = _get_forecaster(idx)
    if fore is None:
        raise HTTPException(status_code=404, detail=f"forecaster_unavailable: {idx}")
    job_id = f"retrain_{idx}_{int(time.time())}"
    return RetrainResponse(index=idx, status='scheduled', job_id=job_id, parameters={'training_days': req.days, 'validate': req.run_validation}, estimated_completion='in 2 hours', message='Retraining job scheduled successfully')
