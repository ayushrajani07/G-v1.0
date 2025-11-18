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
from collections import OrderedDict
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


class RegimeBreach(BaseModel):
    horizon: int
    coverage_window_pct: float
    norm_error_p90: float
    triggered: bool
    reasons: list[str]

class RegimeStatusResponse(BaseModel):
    index: str
    ts_ms: int
    alerts: int
    total_horizons: int
    coverage_min: float
    norm_error_p90_max: float
    breaches: list[RegimeBreach]

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
_CACHE: OrderedDict[Tuple[str,int,str,float,float,float,int,str], ForecastResponse] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SEC = max(0, int(os.environ.get('G6_FORECAST_CACHE_TTL', '30')))
_CACHE_MAX_SIZE = max(1, int(os.environ.get('G6_FORECAST_CACHE_MAX', '500')))
_CACHE_TIME: OrderedDict[Tuple[str,int,str,float,float,float,int,str], float] = OrderedDict()
# Per-key TTL map (seconds) to support adaptive TTL prototype
_CACHE_TTL_MAP: Dict[Tuple[str,int,str,float,float,float,int,str], float] = {}
# Adaptive TTL controls (prototype, behind flag)
_ADAPTIVE_TTL_ENABLED = str(os.environ.get('G6_FORECAST_CACHE_ADAPTIVE_TTL', '0')).lower() in ('1','true','yes','on')
_ADAPTIVE_TTL_MIN = max(1, int(os.environ.get('G6_FORECAST_CACHE_TTL_MIN', '10')))
_ADAPTIVE_TTL_MAX = max(_ADAPTIVE_TTL_MIN, int(os.environ.get('G6_FORECAST_CACHE_TTL_MAX', '60')))
_ADAPTIVE_TTL_IV_REF = max(1e-6, float(os.environ.get('G6_ADAPTIVE_TTL_IV_REF', '0.35')))
_ADAPTIVE_TTL_W_IV = min(1.0, max(0.0, float(os.environ.get('G6_ADAPTIVE_TTL_W_IV', '0.7'))))
_ADAPTIVE_TTL_W_WIN = min(1.0, max(0.0, float(os.environ.get('G6_ADAPTIVE_TTL_W_WIN', '0.3'))))
_CACHE_HITS = 0
_CACHE_MISSES = 0
_CACHE_EVICTIONS = 0
_CACHE_START_TIME = time.time()

# Key normalization (bucket avg_iv) optional controls
_NORMALIZE_AVG_IV = str(os.environ.get('G6_FORECAST_CACHE_NORMALIZE_AVG_IV', '0')).lower() in ('1','true','yes','on')
_AVG_IV_BUCKET_EDGES: list[float] = []
try:
    _AVG_IV_BUCKET_EDGES = [float(p.strip()) for p in os.environ.get('G6_FORECAST_CACHE_AVG_IV_BUCKETS', '0.2,0.35,0.5').split(',') if p.strip()]
    _AVG_IV_BUCKET_EDGES = sorted({e for e in _AVG_IV_BUCKET_EDGES if e > 0.0})
except Exception:
    _AVG_IV_BUCKET_EDGES = [0.2, 0.35, 0.5]
if not _AVG_IV_BUCKET_EDGES:
    _AVG_IV_BUCKET_EDGES = [0.2, 0.35, 0.5]

def _bucket_avg_iv(val: float) -> float:
    """Return bucket edge for avg_iv if normalization enabled else original.

    Uses first edge >= val else returns last edge.
    """
    if not _NORMALIZE_AVG_IV:
        return val
    for edge in _AVG_IV_BUCKET_EDGES:
        if val <= edge:
            return edge
    return _AVG_IV_BUCKET_EDGES[-1]

# --------------------------- Recent Window File Cache ---------------------------
# Cache for recent TP window loaded from CSV to reduce disk I/O and parsing
_RECENT_FILE_CACHE: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
_RECENT_FILE_CACHE_LOCK = threading.Lock()
_RECENT_FILE_CACHE_TTL_SEC = max(0, int(os.environ.get('G6_RECENT_FILE_CACHE_TTL', '60')))
_RECENT_FILE_CACHE_MAX_SIZE = max(1, int(os.environ.get('G6_RECENT_FILE_CACHE_MAX_SIZE', '50')))
_RECENT_FILE_CACHE_HITS = 0
_RECENT_FILE_CACHE_MISSES = 0

def _cache_get(key: Tuple[str,int,str,float,float,float,int,str]) -> Optional[ForecastResponse]:
    if _CACHE_TTL_SEC == 0:
        return None
    with _CACHE_LOCK:
        ts = _CACHE_TIME.get(key)
        if ts is None:
            global _CACHE_MISSES
            _CACHE_MISSES += 1
            # Track Prometheus metric
            try:
                from ..prom_metrics import increment_forecast_cache_miss
                increment_forecast_cache_miss(key[0])  # key[0] is index
            except Exception:
                pass
            return None
        # Determine per-key TTL (adaptive if stored), else fallback to default
        ttl_for_key = _CACHE_TTL_MAP.get(key, float(_CACHE_TTL_SEC))
        if (time.time() - ts) > ttl_for_key:
            # expired - purge
            _CACHE.pop(key, None)
            _CACHE_TIME.pop(key, None)
            _CACHE_TTL_MAP.pop(key, None)
            _CACHE_MISSES += 1
            # Track Prometheus metric
            try:
                from ..prom_metrics import increment_forecast_cache_miss
                increment_forecast_cache_miss(key[0])  # key[0] is index
            except Exception:
                pass
            return None
        # Mark as recently used (LRU)
        _CACHE.move_to_end(key)
        _CACHE_TIME.move_to_end(key)
        global _CACHE_HITS
        _CACHE_HITS += 1
        # Track Prometheus metric
        try:
            from ..prom_metrics import increment_forecast_cache_hit
            increment_forecast_cache_hit(key[0])  # key[0] is index
        except Exception:
            pass
        return _CACHE.get(key)

def _cache_put(key: Tuple[str,int,str,float,float,float,int,str], value: ForecastResponse, ttl_override: float | None = None) -> None:
    if _CACHE_TTL_SEC == 0:
        return
    global _CACHE_EVICTIONS
    with _CACHE_LOCK:
        _CACHE[key] = value
        _CACHE_TIME[key] = time.time()
        # Store per-key TTL (adaptive or default)
        if ttl_override is not None and ttl_override > 0:
            _CACHE_TTL_MAP[key] = float(ttl_override)
        else:
            _CACHE_TTL_MAP[key] = float(_CACHE_TTL_SEC)
        # Move to end to mark as most recently used
        _CACHE.move_to_end(key)
        _CACHE_TIME.move_to_end(key)
        
        # LRU eviction: remove oldest entries when size exceeds max
        while len(_CACHE) > _CACHE_MAX_SIZE:
            # Remove oldest (first) entry
            oldest_key = next(iter(_CACHE))
            _CACHE.pop(oldest_key, None)
            _CACHE_TIME.pop(oldest_key, None)
            _CACHE_TTL_MAP.pop(oldest_key, None)
            _CACHE_EVICTIONS += 1
        
        # Update Prometheus gauge
        try:
            from ..prom_metrics import set_forecast_cache_size
            set_forecast_cache_size(len(_CACHE))
        except Exception:
            pass

@router.get('/cache/stats')
async def cache_stats():
    """Return in-memory forecast cache statistics and recent file cache statistics."""
    now = time.time()
    
    # Forecast cache stats
    with _CACHE_LOCK:
        entries = []
        for k, ts in _CACHE_TIME.items():
            age = now - ts
            ttl_val = _CACHE_TTL_MAP.get(k, float(_CACHE_TTL_SEC))
            entries.append({'key': {
                'index': k[0], 'horizon': k[1], 'quantiles': k[2], 'underlying': k[3], 'avg_iv': k[4], 'minutes_to_expiry': k[5], 'recent_window_size': k[6], 'detail': k[7]
            }, 'age_sec': round(age, 3), 'ttl_sec': ttl_val})
        oldest = max((e['age_sec'] for e in entries), default=0.0)
        newest = min((e['age_sec'] for e in entries), default=0.0)
        hit_ratio = (_CACHE_HITS / (_CACHE_HITS + _CACHE_MISSES)) if (_CACHE_HITS + _CACHE_MISSES) else 0.0
        # TTL remaining stats
        if entries:
            remaining_list = [max(0.0, e['ttl_sec'] - e['age_sec']) for e in entries]
            ttl_remaining_min = min(remaining_list)
            ttl_remaining_max = max(remaining_list)
            ttl_remaining_avg = sum(remaining_list) / len(remaining_list)
        else:
            ttl_remaining_min = ttl_remaining_max = ttl_remaining_avg = 0.0

        # Simple bucketed distribution of TTL remaining (seconds)
        buckets = {'le_15': 0, 'le_30': 0, 'le_45': 0, 'le_60': 0, 'gt_60': 0}
        for r in ([] if not entries else [max(0.0, e['ttl_sec'] - e['age_sec']) for e in entries]):
            if r <= 15:
                buckets['le_15'] += 1
            elif r <= 30:
                buckets['le_30'] += 1
            elif r <= 45:
                buckets['le_45'] += 1
            elif r <= 60:
                buckets['le_60'] += 1
            else:
                buckets['gt_60'] += 1

        runtime_min = max(1e-6, (now - _CACHE_START_TIME) / 60.0)
        eviction_rate_per_min = _CACHE_EVICTIONS / runtime_min

        forecast_cache_stats = {
            'ttl_sec_default': _CACHE_TTL_SEC,
            'adaptive': _ADAPTIVE_TTL_ENABLED,
            'ttl_min': _ADAPTIVE_TTL_MIN,
            'ttl_max': _ADAPTIVE_TTL_MAX,
            'max_size': _CACHE_MAX_SIZE,
            'size': len(entries),
            'hits': _CACHE_HITS,
            'misses': _CACHE_MISSES,
            'evictions': _CACHE_EVICTIONS,
            'eviction_rate_per_min': round(eviction_rate_per_min, 4),
            'hit_ratio': round(hit_ratio, 4),
            'oldest_age_sec': oldest,
            'newest_age_sec': newest,
            'ttl_remaining_min_sec': round(ttl_remaining_min, 3),
            'ttl_remaining_max_sec': round(ttl_remaining_max, 3),
            'ttl_remaining_avg_sec': round(ttl_remaining_avg, 3),
            'ttl_distribution': buckets,
            'avg_iv_normalization_enabled': _NORMALIZE_AVG_IV,
            'avg_iv_bucket_edges': _AVG_IV_BUCKET_EDGES,
            'entries': entries[:50],  # cap detail
        }
    
    # Recent file cache stats
    with _RECENT_FILE_CACHE_LOCK:
        file_entries = []
        for k, entry in _RECENT_FILE_CACHE.items():
            age = now - entry['ts']
            file_entries.append({
                'key': {
                    'index': k[0],
                    'date': k[1],
                    'window_size': k[2],
                },
                'age_sec': round(age, 3),
                'row_count': len(entry.get('rows', [])),
            })
        file_oldest = max((e['age_sec'] for e in file_entries), default=0.0)
        file_newest = min((e['age_sec'] for e in file_entries), default=0.0)
        file_hit_ratio = (_RECENT_FILE_CACHE_HITS / (_RECENT_FILE_CACHE_HITS + _RECENT_FILE_CACHE_MISSES)) if (_RECENT_FILE_CACHE_HITS + _RECENT_FILE_CACHE_MISSES) else 0.0
        recent_file_cache_stats = {
            'ttl_sec': _RECENT_FILE_CACHE_TTL_SEC,
            'max_size': _RECENT_FILE_CACHE_MAX_SIZE,
            'current_entries': len(file_entries),
            'hits': _RECENT_FILE_CACHE_HITS,
            'misses': _RECENT_FILE_CACHE_MISSES,
            'hit_ratio': round(file_hit_ratio, 4),
            'oldest_age_sec': file_oldest,
            'newest_age_sec': file_newest,
            'entries': file_entries[:50],  # cap detail
        }
    
    return {
        'forecast_cache': forecast_cache_stats,
        'recent_file_cache': recent_file_cache_stats,
    }

@router.post('/cache/clear')
async def cache_clear():
    """Clear the in-memory forecast cache and recent file cache, and reset counters."""
    global _CACHE_HITS, _CACHE_MISSES, _RECENT_FILE_CACHE_HITS, _RECENT_FILE_CACHE_MISSES
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE_TIME.clear()
        _CACHE_HITS = 0
        _CACHE_MISSES = 0
    with _RECENT_FILE_CACHE_LOCK:
        _RECENT_FILE_CACHE.clear()
        _RECENT_FILE_CACHE_HITS = 0
        _RECENT_FILE_CACHE_MISSES = 0
    return {'status': 'ok', 'cleared': True, 'caches_cleared': ['forecast_cache', 'recent_file_cache']}

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
    
    Uses file-level cache with mtime awareness to avoid repeated disk I/O.
    """
    if limit <= 0:
        return []
    
    # Cache lookup
    today = time.strftime('%Y-%m-%d')
    cache_key = (index.upper(), today, limit)
    
    # Try cache first if enabled
    if _RECENT_FILE_CACHE_TTL_SEC > 0:
        with _RECENT_FILE_CACHE_LOCK:
            global _RECENT_FILE_CACHE_HITS, _RECENT_FILE_CACHE_MISSES
            
            # First try exact match
            cached_entry = _RECENT_FILE_CACHE.get(cache_key)
            
            # If no exact match, look for larger windows we can reuse
            if cached_entry is None:
                idx_upper = index.upper()
                for (cached_idx, cached_date, cached_limit), entry in _RECENT_FILE_CACHE.items():
                    if cached_idx == idx_upper and cached_date == today and cached_limit >= limit:
                        cached_entry = entry
                        break
            
            if cached_entry is not None:
                cached_rows = cached_entry.get('rows')
                cached_mtime = cached_entry.get('mtime')
                cached_ts = cached_entry.get('ts')
                cached_path = cached_entry.get('path')
                
                # Check TTL
                if (time.time() - cached_ts) <= _RECENT_FILE_CACHE_TTL_SEC:
                    # Check mtime if path exists
                    try:
                        if cached_path and Path(cached_path).exists():
                            current_mtime = os.path.getmtime(cached_path)
                            if abs(current_mtime - cached_mtime) < 0.001:  # mtime unchanged
                                _RECENT_FILE_CACHE_HITS += 1
                                _LOG.debug(f"recent_file_cache HIT: {cache_key}")
                                # Track Prometheus metric
                                try:
                                    from ..prom_metrics import increment_recent_window_cache_hit
                                    increment_recent_window_cache_hit(index.upper())
                                except Exception:
                                    pass
                                # If cached has more rows than requested, slice last N
                                if len(cached_rows) >= limit:
                                    return cached_rows[-limit:]
                                return cached_rows
                    except Exception:
                        pass
            
            _RECENT_FILE_CACHE_MISSES += 1
            _LOG.debug(f"recent_file_cache MISS: {cache_key}")
            # Track Prometheus metric
            try:
                from ..prom_metrics import increment_recent_window_cache_miss
                increment_recent_window_cache_miss(index.upper())
            except Exception:
                pass
    
    # Cache miss or disabled - load from disk
    return _load_recent_window_impl(index, limit, today, cache_key)


def _load_recent_window_impl(index: str, limit: int, today: str, cache_key: Tuple[str, str, int]) -> list[list[float]]:
    """Implementation of recent window loading with cache update."""

    root = _project_root() / 'data' / 'g6_data'
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
        
        # Update cache if enabled
        if _RECENT_FILE_CACHE_TTL_SEC > 0:
            with _RECENT_FILE_CACHE_LOCK:
                # Evict oldest entry if cache is full
                if len(_RECENT_FILE_CACHE) >= _RECENT_FILE_CACHE_MAX_SIZE:
                    # Find and remove the oldest entry by timestamp
                    oldest_key = min(_RECENT_FILE_CACHE.keys(), 
                                    key=lambda k: _RECENT_FILE_CACHE[k]['ts'])
                    _RECENT_FILE_CACHE.pop(oldest_key, None)
                    _LOG.debug(f"recent_file_cache evicted oldest entry: {oldest_key}")
                
                # Store in cache
                mtime = os.path.getmtime(path)
                _RECENT_FILE_CACHE[cache_key] = {
                    'rows': rows,
                    'mtime': mtime,
                    'ts': time.time(),
                    'path': str(path),
                }
                _LOG.debug(f"recent_file_cache stored: {cache_key}")
                
                # Update Prometheus gauge
                try:
                    from ..prom_metrics import set_recent_window_cache_size
                    set_recent_window_cache_size(len(_RECENT_FILE_CACHE))
                except Exception:
                    pass
        
        return rows
    except Exception as e:
        _LOG.warning(f"recent_window_load_failed index={index} path={path}: {e}")
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

# --------------------------- Endpoints ---------------------------
def _compute_adaptive_ttl(
    index: str,
    horizon: int,
    underlying: float,
    avg_iv: float,
    minutes_to_expiry: float,
    recent_window: list[list[float]] | None,
) -> float | None:
    """Compute adaptive TTL seconds based on simple volatility proxies.

    Uses weighted combination of:
    - avg_iv normalized to reference (_ADAPTIVE_TTL_IV_REF)
    - recent window normalized return volatility

    Returns None when adaptive TTL is disabled.
    """
    if not _ADAPTIVE_TTL_ENABLED:
        return None
    try:
        # Normalize IV approximately to 0..1 by comparing to reference
        iv_norm = max(0.0, min(1.0, float(avg_iv) / float(_ADAPTIVE_TTL_IV_REF)))
        iv_norm = min(iv_norm, 2.0) / 2.0  # cap at 2x ref, then map to 0..1

        # Recent window normalized volatility (std of absolute returns)
        win_norm = 0.0
        vals: list[float] = []
        if recent_window:
            try:
                vals = [float(row[0]) for row in recent_window if row and len(row) > 0]
            except Exception:
                vals = []
        if len(vals) >= 8:  # need at least 8 points for a rough estimate
            # Use last up to 60 points
            seg = vals[-60:]
            rets: list[float] = []
            for i in range(1, len(seg)):
                a = seg[i-1]
                b = seg[i]
                denom = max(abs(b), 1e-6)
                rets.append(abs(b - a) / denom)
            if rets:
                # population stddev
                m = sum(rets) / len(rets)
                var = sum((r - m) ** 2 for r in rets) / len(rets)
                std = var ** 0.5
                # Normalize against 1% baseline
                win_norm = max(0.0, min(1.0, std / 0.01))
        # Weighted vol score
        w_sum = max(1e-6, (_ADAPTIVE_TTL_W_IV + _ADAPTIVE_TTL_W_WIN))
        vol_score = (_ADAPTIVE_TTL_W_IV * iv_norm + _ADAPTIVE_TTL_W_WIN * win_norm) / w_sum
        vol_score = max(0.0, min(1.0, vol_score))
        ttl_span = float(max(0, _ADAPTIVE_TTL_MAX - _ADAPTIVE_TTL_MIN))
        ttl = float(_ADAPTIVE_TTL_MAX) - vol_score * ttl_span
        # Final clamp
        if ttl < _ADAPTIVE_TTL_MIN:
            ttl = float(_ADAPTIVE_TTL_MIN)
        if ttl > _ADAPTIVE_TTL_MAX:
            ttl = float(_ADAPTIVE_TTL_MAX)
        return ttl
    except Exception:
        return None

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
    # Apply avg_iv bucket normalization ONLY to cache key (response retains original avg_iv)
    avg_iv_bucket = _bucket_avg_iv(avg_iv)
    cache_key = (idx, horizon, quantiles, underlying, avg_iv_bucket, minutes_to_expiry, recent_window_size, detail_normalized)
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
    # Compute adaptive TTL (if enabled) and store alongside entry
    ttl_override = _compute_adaptive_ttl(idx, horizon, underlying, avg_iv, minutes_to_expiry, recent_window)
    _cache_put(cache_key, resp, ttl_override=ttl_override)
    
    # Track Prometheus latency metric
    try:
        from ..prom_metrics import observe_forecast_latency
        observe_forecast_latency(idx, horizon, latency_ms)
    except Exception:
        pass

    # Rolling MAE: log p50 forecast for future evaluation (Phase 10 initial stub)
    try:
        from ..rolling_mae import log_forecast_event, ensure_started  # type: ignore
        ensure_started()
        log_forecast_event(idx, horizon, now_ms, p50, underlying, band_low, band_high)
    except Exception:
        pass
    
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

@router.get('/regime/breaches')
async def regime_breaches(index: str = Query(..., description="Index e.g. NIFTY")):
    """Return flat list of regime breaches for an index (test harness expects list)."""
    try:
        from ..regime_alerts import get_regime_summary  # type: ignore
        summary = get_regime_summary(index=index)
        breaches = summary.get('breaches', []) if isinstance(summary, dict) else []
        return breaches
    except Exception:
        return []

@router.get('/metrics/compare')
async def metrics_compare(
    index: str = Query(..., description="Index e.g. NIFTY"),
    horizon: int = Query(60, ge=1, le=720),
    include_drift: int = Query(0, ge=0, le=1, description="Set to 1 to include drift summary"),
):
    """Return metrics comparison (rolling vs EMA) and optional drift summary for index,horizon.

    Provides fields needed by test_ml_regime_and_drift_endpoints.
    """
    try:
        from ..rolling_mae import get_metric_comparison, get_drift_summary, ensure_started  # type: ignore
        ensure_started()
        comp = get_metric_comparison(index=index, horizon=horizon)
        entry = None
        for ent in comp.get('entries', []):
            if int(ent.get('horizon', -1)) == int(horizon):
                entry = ent
                break
        if entry is None:
            # return minimal stub
            base = {"index": index.upper(), "horizon": horizon, "available": False}
            if include_drift:
                drift = get_drift_summary(index.upper(), horizon)
                base['drift_summary'] = drift
            return base
        resp = {"index": index.upper(), "horizon": horizon}
        # expose selected fields directly
        for k in [
            'mae_window','mae_short','mae_drift_ratio','coverage_window_pct','coverage_short_pct','coverage_drift_delta_pct',
            'norm_error_window','norm_error_short','norm_error_drift_ratio','count_window'
        ]:
            if k in entry:
                resp[k] = entry[k]
        if include_drift:
            resp['drift_summary'] = get_drift_summary(index.upper(), horizon)
            # Export drift ratios to Prometheus
            try:
                from ..prom_metrics import set_forecast_drift_ratios, set_forecast_coverage_drift  # type: ignore
                drift = resp['drift_summary']
                set_forecast_drift_ratios(index.upper(), horizon, float(drift.get('mae_ratio',0.0)), float(drift.get('norm_ratio',0.0)))
                set_forecast_coverage_drift(index.upper(), horizon, float(drift.get('coverage_delta_pct',0.0)))
            except Exception:
                pass
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"metrics_compare_failed: {e}")


@router.get('/regime/status', response_model=RegimeStatusResponse | Dict[str, RegimeStatusResponse])
async def regime_status(index: Optional[str] = Query(None, description="Optional index e.g. NIFTY")):
    """Return last computed regime evaluation summary.

    - If index provided, returns a single summary object (or 404 if missing).
    - If index omitted, returns a mapping {index -> summary} for all tracked indices.
    """
    try:
        from ..regime_alerts import get_regime_summary  # type: ignore
        data = get_regime_summary(index=index)
        if index:
            if not data:
                raise HTTPException(status_code=404, detail=f"no_regime_summary: {index.upper()}")
            return data  # type: ignore[return-value]
        return data  # type: ignore[return-value]
    except HTTPException:
        raise
    except Exception as e:
        _LOG.warning(f"regime_status_failed: {e}")
        raise HTTPException(status_code=500, detail="regime_status_failed")


@router.get('/regime/breaches', response_model=list[RegimeBreach])
async def regime_breaches(index: str = Query(..., description="Index e.g. NIFTY")):
    """Return only the breaches array for the given index for easy table rendering.

    If no summary is available yet, returns an empty list.
    """
    try:
        from ..regime_alerts import get_regime_summary  # type: ignore
        data = get_regime_summary(index=index)
        if not data:
            return []
        breaches = data.get("breaches") or []
        # Ensure list of objects
        if isinstance(breaches, list):
            return breaches
        return []
    except Exception as e:
        _LOG.warning(f"regime_breaches_failed: {e}")
        raise HTTPException(status_code=500, detail="regime_breaches_failed")

@router.get('/regime/dynamic_thresholds')
async def regime_dynamic_thresholds(
    index: str = Query(..., description="Index e.g. NIFTY"),
    include_percentiles: int = Query(1, ge=0, le=1, description="Include raw percentile baselines (0/1)"),
):
    """Return dynamic drift threshold evaluation per horizon for an index.

    Response schema:
    {
      "index": "NIFTY",
      "generated_at": <epoch_ms>,
      "autotune_enabled": true,
      "horizons": [
        {
          "horizon": 60,
          "static": {"mae_warn":1.5,"mae_crit":2.0,"norm_warn":1.3,"norm_crit":1.7,"coverage_drop_warn":-10,"coverage_drop_crit":-20},
          "dynamic": {"used": true, "mae_warn":1.42, ...},
          "percentiles": {"mae_ratio": {"p50":1.1,"p85":1.42,"p95":1.61}, ...},
          "counts": {"mae": 48, "norm": 48, "coverage": 48},
          "latest_metrics": {"mae_ratio":1.55,"norm_ratio":1.34,"coverage_delta":-12.0},
          "breach": {"drift_triggered": true, "drift_reasons": ["mae_ratio>=1.5"]}
        }, ...
      ]
    }
    """
    try:
        from ..regime_alerts import get_regime_summary  # type: ignore
        from ..rolling_mae import get_drift_baselines  # type: ignore
        summary = get_regime_summary(index=index)
        if not summary:
            return {"index": index.upper(), "generated_at": int(time.time()*1000), "autotune_enabled": False, "horizons": []}
        autotune_enabled = bool(summary.get("autotune_enabled", False))
        base_percentiles = get_drift_baselines(index.upper()) if include_percentiles == 1 else {}
        breaches = summary.get("breaches", []) or []
        horizons_out = []
        for b in breaches:
            h = int(b.get("horizon", -1))
            key = (index.upper(), h)
            pct_entry = base_percentiles.get(key, {}) if include_percentiles == 1 else {}
            dyn = b.get("dynamic_thresholds", {}) or {}
            horizons_out.append({
                "horizon": h,
                "static": {
                    "mae_warn": summary.get("mae_drift_ratio_warn"),
                    "mae_crit": summary.get("mae_drift_ratio_crit"),
                    "norm_warn": summary.get("norm_drift_ratio_warn"),
                    "norm_crit": summary.get("norm_drift_ratio_crit"),
                    "coverage_drop_warn": summary.get("coverage_drift_drop_warn"),
                    "coverage_drop_crit": summary.get("coverage_drift_drop_crit"),
                },
                "dynamic": dyn if autotune_enabled else {"used": False},
                "percentiles": pct_entry if include_percentiles == 1 else {},
                "counts": pct_entry.get("counts", {}) if pct_entry else {},
                "latest_metrics": {
                    "mae_ratio": b.get("mae_drift_ratio"),
                    "norm_ratio": b.get("norm_error_drift_ratio"),
                    "coverage_delta": b.get("coverage_drift_delta_pct"),
                },
                "breach": {
                    "drift_triggered": b.get("drift_triggered", False),
                    "drift_reasons": b.get("drift_reasons", []),
                },
            })
        return {
            "index": index.upper(),
            "generated_at": int(time.time()*1000),
            "autotune_enabled": autotune_enabled,
            "horizons": horizons_out,
        }
    except Exception as e:
        _LOG.warning(f"regime_dynamic_thresholds_failed: {e}")
        raise HTTPException(status_code=500, detail="regime_dynamic_thresholds_failed")

@router.post('/metrics/flush')
async def metrics_flush():
    """Force flush rolling MAE & coverage state to persistence file (Phase 10).

    Returns summary of persisted keys; no-op if persistence disabled.
    """
    try:
        from ..rolling_mae import ensure_started, force_flush_state  # type: ignore
        ensure_started()
        result = force_flush_state()
        return {"status": "ok", **result}
    except Exception as e:
        _LOG.warning(f"metrics_flush_failed: {e}")
        raise HTTPException(status_code=500, detail="metrics_flush_failed")

@router.get('/metrics/compare')
async def metrics_compare(
    index: Optional[str] = Query(None, description="Optional index filter e.g. NIFTY"),
    horizon: Optional[int] = Query(None, ge=1, le=720, description="Optional horizon filter in minutes"),
    include_drift: int = Query(0, ge=0, le=1, description="Include drift summary when index provided (0/1)"),
):
    """Return comparison of rolling window vs EMA metrics (Phase 10 diagnostic).

    Supports optional filtering by index & horizon. Includes:
    - window & EMA MAE
    - window & EMA coverage
    - window & EMA normalized error
    - p50/p90 percentiles for error, normalized error, band width (if >=5 samples)
    - last evaluation timestamp (epoch ms)
    """
    try:
        from ..rolling_mae import ensure_started, get_metric_comparison  # type: ignore
        ensure_started()
        result = get_metric_comparison(index=index, horizon=horizon)
        if include_drift == 1 and index:
            try:
                from ..drift_metrics import get_drift_summary  # type: ignore
                drift = get_drift_summary(index=index)
                if isinstance(result, dict):
                    result["drift_summary"] = drift
            except Exception:
                pass
        return result
    except Exception as e:
        _LOG.warning(f"metrics_compare_failed: {e}")
        raise HTTPException(status_code=500, detail="metrics_compare_failed")

@router.get('/metrics/decay/validate')
async def metrics_decay_validate():
    """Return decay configuration validation (precedence & derived alpha)."""
    try:
        from ..rolling_mae import ensure_started, validate_decay_config  # type: ignore
        ensure_started()
        return validate_decay_config()
    except Exception as e:
        _LOG.warning(f"metrics_decay_validate_failed: {e}")
        raise HTTPException(status_code=500, detail="metrics_decay_validate_failed")

@router.get('/drift')
async def drift_metrics(
    index: str = Query(..., description="Index name (e.g., NIFTY, BANKNIFTY)"),
    features: Optional[str] = Query(None, description="Comma-separated feature names (empty = all)"),
    full: int = Query(0, ge=0, le=1, description="Include full bin-level details (0=summary, 1=full)"),
):
    """Get drift metrics for feature distributions (Phase 10).
    
    Compares recent feature distributions against baseline (last 30 days).
    Auto-creates baseline if missing.
    
    Returns:
        JSON with drift metrics per feature:
        {
            "index": "NIFTY",
            "baseline_days": 30,
            "recent_rows": 300,
            "generated_at": <epoch_ms>,
            "features": {
                "feature_name": {
                    "psi": 0.18,
                    "ks_pvalue": 0.045,
                    "mean_delta": -0.012,
                    "var_delta": 0.031,
                    "alert": false,
                    "bins": [...] (if full=1)
                }
            },
            "summary": {
                "total_features": 25,
                "alerts": 2
            }
        }
    """
    try:
        from src.ml.drift_monitor import create_drift_monitor_from_env
    except ImportError:
        _LOG.error("Failed to import drift_monitor module")
        raise HTTPException(status_code=500, detail="drift_monitor_unavailable")
    
    try:
        # Create drift monitor from environment variables
        monitor = create_drift_monitor_from_env()
        
        # Parse feature list
        feature_list = None
        if features:
            feature_list = [f.strip() for f in features.split(',') if f.strip()]
        
        # Get or create baseline
        baseline = monitor.get_or_create_baseline(index, features=feature_list)
        
        # Get recent window
        recent = monitor.compute_feature_distributions(
            index=index,
            lookback_days=0,  # Use recent_rows instead
            features=feature_list,
        )
        
        # Calculate drift metrics
        drift_metrics = monitor.calculate_drift_metrics(baseline, recent)
        
        # Build response
        features_response = {}
        total_alerts = 0
        
        for feature_name, metrics in drift_metrics.items():
            feature_data = {
                "psi": metrics["psi"],
                "ks_pvalue": metrics["ks_pvalue"],
                "mean_delta": metrics["mean_delta"],
                "var_delta": metrics["var_delta"],
                "alert": metrics["alert_flag"],
            }
            
            # Include bins if full detail requested
            if full == 1:
                feature_data["bins"] = metrics["bins"]
                feature_data["ks_statistic"] = metrics["ks_statistic"]
                feature_data["mean_delta_zscore"] = metrics["mean_delta_zscore"]
                feature_data["alert_reasons"] = metrics["alert_reasons"]
            
            features_response[feature_name] = feature_data
            
            if metrics["alert_flag"]:
                total_alerts += 1
        
        return {
            "index": index,
            "baseline_days": monitor.baseline_days,
            "recent_rows": monitor.recent_rows,
            "generated_at": int(time.time() * 1000),
            "features": features_response,
            "summary": {
                "total_features": len(drift_metrics),
                "alerts": total_alerts,
            },
        }
    
    except Exception as e:
        _LOG.error(f"drift_metrics failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"drift_metrics_failed: {str(e)}")
