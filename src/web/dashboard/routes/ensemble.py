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
import logging, os, threading, json
try:
    # Stability helpers (best effort import; endpoint tolerates absence)
    from scripts.ml.validate_drift_threshold_stability import load_artifacts, compute_report  # type: ignore
except Exception:  # pragma: no cover
    load_artifacts = None  # type: ignore
    compute_report = None  # type: ignore
from datetime import datetime, time as dtime, timedelta, timezone
from collections import OrderedDict
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.path_forecast.ensemble import EnsembleConfig, EnsembleForecaster
from src.path_forecast.learned_ensemble import LearnedEnsembleForecaster
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

class EnsembleConfigResponse(BaseModel):
    index: str = Field(..., description="Index e.g. NIFTY")
    config_file: str | None = Field(None, description="Resolved config file path if present")
    loaded: bool = Field(False, description="True if config parsed and forecaster initialized")
    components: Dict[str, bool] = Field(default_factory=dict, description="Component enablement flags")
    weighting: Dict[str, float] = Field(default_factory=dict, description="Active weighting parameters")
    errors: str | None = Field(None, description="Initialization error, if any")

# --------------------------- Helpers ---------------------------
_def_components = ['baseline', 'gbrt', 'retrieval', 'conformal']

# --------------------------- Feature Importance Helpers ---------------------------
_FI_HISTORY_PATH = Path("reports") / "feature_importance_history.json"

def _read_fi_history(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or _FI_HISTORY_PATH
    try:
        if not p.is_file():
            return []
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []

# --------------------------- Manifest Chain-of-Trust ---------------------------
def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def _sha256_json(obj: dict) -> str:
    import hashlib
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()

def _validate_manifest_chain(manifests_dir: Path, max_depth: int = 50) -> dict[str, Any]:
    latest_ptr = manifests_dir / 'latest.json'
    if not latest_ptr.is_file():
        return {"available": False}
    ptr = _load_json(latest_ptr)
    if not ptr:
        return {"available": False}
    mf = ptr.get('manifest_file')
    if not mf:
        return {"available": False}
    cur = manifests_dir / mf
    depth = 0
    chain: list[dict[str, Any]] = []
    while cur.is_file() and depth < max_depth:
        m = _load_json(cur)
        if not m:
            break
        # compute expected chain signature
        expected = _sha256_json({
            'prev_signature': m.get('prev_signature'),
            'base_signature': m.get('base_signature'),
            'promoted_at': m.get('promoted_at'),
            'indices': m.get('indices'),
        })
        ok = (m.get('signature') == expected)
        chain.append({
            'file': cur.name,
            'signature_ok': ok,
            'promoted_at': m.get('promoted_at'),
            'prev_signature': m.get('prev_signature'),
            'base_signature': m.get('base_signature'),
        })
        if not ok:
            break
        prev = m.get('previous_manifest')
        if not prev:
            break
        cur = manifests_dir / prev
        depth += 1
    valid = all(e.get('signature_ok') for e in chain) if chain else False
    return {
        'available': True,
        'valid': valid,
        'length': len(chain),
        'chain': chain,
    }

@router.get('/regime/threshold_manifest_chain')
async def threshold_manifest_chain():
    """Validate chain-of-trust across drift manifests and return details."""
    try:
        mdir = Path('metrics') / 'drift_manifests'
        return _validate_manifest_chain(mdir)
    except Exception as e:
        _LOG.warning(f"threshold_manifest_chain_failed: {e}")
        return {"available": False, "valid": False, "error": "exception"}

def _quantile_to_label(q: float) -> str:
    """Convert quantile float to stable label string.
    
    Examples: 0.1 -> 'p10', 0.5 -> 'p50', 0.95 -> 'p95'
    """
    # Round to avoid floating point precision issues
    pct = round(q * 100)
    return f"p{pct}"

# --------------------------- Forecast Cache ---------------------------
class ForecastCache:
    """Encapsulated forecast cache with adaptive TTL and thread safety."""
    
    def __init__(self):
        self._cache: OrderedDict[Tuple[str,int,str,float,float,float,int,str], ForecastResponse] = OrderedDict()
        self._lock = threading.Lock()
        self._ttl_sec = max(0, int(os.environ.get('G6_FORECAST_CACHE_TTL', '30')))
        self._max_size = max(1, int(os.environ.get('G6_FORECAST_CACHE_MAX', '500')))
        self._time: OrderedDict[Tuple[str,int,str,float,float,float,int,str], float] = OrderedDict()
        self._ttl_map: Dict[Tuple[str,int,str,float,float,float,int,str], float] = {}
        
        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._start_time = time.time()
        
        # Adaptive TTL controls
        self._adaptive_enabled = str(os.environ.get('G6_FORECAST_CACHE_ADAPTIVE_TTL', '0')).lower() in ('1','true','yes','on')
        self._adaptive_min = max(1, int(os.environ.get('G6_FORECAST_CACHE_TTL_MIN', '10')))
        self._adaptive_max = max(self._adaptive_min, int(os.environ.get('G6_FORECAST_CACHE_TTL_MAX', '60')))
        self._adaptive_iv_ref = max(1e-6, float(os.environ.get('G6_ADAPTIVE_TTL_IV_REF', '0.35')))
        self._adaptive_w_iv = min(1.0, max(0.0, float(os.environ.get('G6_ADAPTIVE_TTL_W_IV', '0.7'))))
        self._adaptive_w_win = min(1.0, max(0.0, float(os.environ.get('G6_ADAPTIVE_TTL_W_WIN', '0.3'))))

    def get(self, key: Tuple[str,int,str,float,float,float,int,str]) -> Optional[ForecastResponse]:
        if self._ttl_sec == 0:
            return None
            
        with self._lock:
            ts = self._time.get(key)
            if ts is None:
                self._misses += 1
                try:
                    from ..prom_metrics import increment_forecast_cache_miss
                    increment_forecast_cache_miss(key[0])
                except Exception:
                    pass
                return None
                
            # Check TTL
            ttl_for_key = self._ttl_map.get(key, float(self._ttl_sec))
            if (time.time() - ts) > ttl_for_key:
                # Expired
                self._cache.pop(key, None)
                self._time.pop(key, None)
                self._ttl_map.pop(key, None)
                self._misses += 1
                try:
                    from ..prom_metrics import increment_forecast_cache_miss
                    increment_forecast_cache_miss(key[0])
                except Exception:
                    pass
                return None
                
            # Hit
            self._cache.move_to_end(key)
            self._time.move_to_end(key)
            self._hits += 1
            try:
                from ..prom_metrics import increment_forecast_cache_hit
                increment_forecast_cache_hit(key[0])
            except Exception:
                pass
            return self._cache.get(key)

    def put(self, key: Tuple[str,int,str,float,float,float,int,str], value: ForecastResponse, ttl_override: float | None = None) -> None:
        if self._ttl_sec == 0:
            return
            
        with self._lock:
            self._cache[key] = value
            self._time[key] = time.time()
            
            if ttl_override is not None and ttl_override > 0:
                self._ttl_map[key] = float(ttl_override)
            else:
                self._ttl_map[key] = float(self._ttl_sec)
                
            self._cache.move_to_end(key)
            self._time.move_to_end(key)
            
            # Eviction
            while len(self._cache) > self._max_size:
                oldest_key = next(iter(self._cache))
                self._cache.pop(oldest_key, None)
                self._time.pop(oldest_key, None)
                self._ttl_map.pop(oldest_key, None)
                self._evictions += 1
                
            try:
                from ..prom_metrics import set_forecast_cache_size
                set_forecast_cache_size(len(self._cache))
            except Exception:
                pass

    def compute_adaptive_ttl(self, avg_iv: float, recent_window: list[list[float]] | None) -> float | None:
        if not self._adaptive_enabled:
            return None
        try:
            iv_norm = max(0.0, min(1.0, float(avg_iv) / float(self._adaptive_iv_ref)))
            iv_norm = min(iv_norm, 2.0) / 2.0

            win_norm = 0.0
            vals: list[float] = []
            if recent_window:
                try:
                    vals = [float(row[0]) for row in recent_window if row and len(row) > 0]
                except Exception:
                    vals = []
            if len(vals) >= 8:
                seg = vals[-60:]
                rets: list[float] = []
                for i in range(1, len(seg)):
                    a = seg[i-1]
                    b = seg[i]
                    denom = max(abs(b), 1e-6)
                    rets.append(abs(b - a) / denom)
                if rets:
                    m = sum(rets) / len(rets)
                    var = sum((r - m) ** 2 for r in rets) / len(rets)
                    std = var ** 0.5
                    win_norm = max(0.0, min(1.0, std / 0.01))
            
            w_sum = max(1e-6, (self._adaptive_w_iv + self._adaptive_w_win))
            vol_score = (self._adaptive_w_iv * iv_norm + self._adaptive_w_win * win_norm) / w_sum
            vol_score = max(0.0, min(1.0, vol_score))
            
            ttl_span = float(max(0, self._adaptive_max - self._adaptive_min))
            ttl = float(self._adaptive_max) - vol_score * ttl_span
            
            return max(float(self._adaptive_min), min(float(self._adaptive_max), ttl))
        except Exception:
            return None

    def get_stats(self) -> dict:
        now = time.time()
        with self._lock:
            entries = []
            for k, ts in self._time.items():
                age = now - ts
                ttl_val = self._ttl_map.get(k, float(self._ttl_sec))
                entries.append({
                    'key': {
                        'index': k[0], 'horizon': k[1], 'quantiles': k[2], 
                        'underlying': k[3], 'avg_iv': k[4], 'minutes_to_expiry': k[5], 
                        'recent_window_size': k[6], 'detail': k[7]
                    },
                    'age_sec': round(age, 3),
                    'ttl_sec': ttl_val
                })
            
            total_reqs = self._hits + self._misses
            hit_ratio = (self._hits / total_reqs) if total_reqs > 0 else 0.0
            
            runtime_min = max(1e-6, (now - self._start_time) / 60.0)
            eviction_rate = self._evictions / runtime_min
            
            return {
                'ttl_sec_default': self._ttl_sec,
                'adaptive': self._adaptive_enabled,
                'ttl_min': self._adaptive_min,
                'ttl_max': self._adaptive_max,
                'max_size': self._max_size,
                'size': len(self._cache),
                'hits': self._hits,
                'misses': self._misses,
                'evictions': self._evictions,
                'eviction_rate_per_min': round(eviction_rate, 3),
                'hit_ratio': round(hit_ratio, 4),
                'oldest_age_sec': max((e['age_sec'] for e in entries), default=0.0),
                'newest_age_sec': min((e['age_sec'] for e in entries), default=0.0),
                'entries': entries
            }

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._time.clear()
            self._ttl_map.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._start_time = time.time()

# Singleton instance
_FORECAST_CACHE = ForecastCache()

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

@router.get('/cache/stats')
async def cache_stats():
    """Return in-memory forecast cache statistics and recent file cache statistics.

    Stable primary cache diagnostics endpoint. Alias available at /cache_metrics for legacy scripts.
    """
    # Forecast cache stats
    forecast_stats = _FORECAST_CACHE.get_stats()
    
    # Recent file cache stats
    with _RECENT_FILE_CACHE_LOCK:
        file_entries = len(_RECENT_FILE_CACHE)
        file_hits = _RECENT_FILE_CACHE_HITS
        file_misses = _RECENT_FILE_CACHE_MISSES
        
    return {
        'forecast_cache': forecast_stats,
        'recent_file_cache': {
            'size': file_entries,
            'hits': file_hits,
            'misses': file_misses,
            'ttl_sec': _RECENT_FILE_CACHE_TTL_SEC,
            'max_size': _RECENT_FILE_CACHE_MAX_SIZE
        }
    }

@router.get('/cache_metrics')
async def cache_metrics_alias():
    """Alias for /cache/stats (Phase 9 legacy load tester expected /cache_metrics)."""
    return await cache_stats()

@router.post('/cache/clear')
async def cache_clear():
    """Clear the in-memory forecast cache and recent file cache, and reset counters."""
    global _RECENT_FILE_CACHE_HITS, _RECENT_FILE_CACHE_MISSES
    
    _FORECAST_CACHE.clear()
    
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
        
        # Phase 13: Use LearnedEnsembleForecaster if strategy is 'learned'
        if cfg.weighting_strategy == "learned":
            # Assume meta-model is at models/ml/meta_model_v1.joblib (or configured)
            meta_path = Path("models/ml/meta_model_v1.joblib")
            fore = LearnedEnsembleForecaster(cfg, meta_model_path=meta_path)
        else:
            fore = EnsembleForecaster(cfg)
            
        _configs[idx] = cfg
        _forecasters[idx] = fore
        _LOG.info(f"Ensemble forecaster initialized for {idx} (strategy={cfg.weighting_strategy})")
        return fore
    except Exception as e:  # pragma: no cover
        _init_errors[idx] = f"init_failed: {e}"
        _LOG.error(f"Forecaster init failed for {idx}: {e}", exc_info=True)
        return None

@router.get('/config', response_model=EnsembleConfigResponse)
async def ensemble_config(index: str = Query(..., description="Index e.g. NIFTY")):
    """Return parsed ensemble configuration for an index.

    Minimal stub endpoint to confirm config presence for newly added indices (e.g. SENSEX).
    Always attempts lazy initialization so that forecaster/config are cached for subsequent forecasts.
    """
    idx = index.upper().strip()
    cfg_path = _config_dir() / f"{idx.lower()}_ensemble_config.json"
    fore = _get_forecaster(idx)  # triggers lazy load
    cfg = _configs.get(idx)
    loaded = fore is not None and cfg is not None
    components: Dict[str, bool] = {}
    weighting: Dict[str, float] = {}
    if cfg:
        try:
            components = {
                'baseline': cfg.baseline_enabled,
                'gbrt': cfg.gbrt_enabled,
                'retrieval': cfg.retrieval_enabled,
                'conformal': cfg.conformal_enabled,
            }
            weighting = {
                'confidence_threshold': cfg.confidence_threshold,
                'weights_high_conf_gbrt': cfg.weights_high_conf_gbrt,
                'weights_high_conf_retrieval': cfg.weights_high_conf_retrieval,
                'weights_low_conf_gbrt': cfg.weights_low_conf_gbrt,
                'weights_low_conf_retrieval': cfg.weights_low_conf_retrieval,
                'min_candidates_threshold': cfg.min_candidates_threshold,
            }
        except Exception:
            pass
    return EnsembleConfigResponse(
        index=idx,
        config_file=str(cfg_path) if cfg_path.exists() else None,
        loaded=loaded,
        components=components,
        weighting=weighting,
        errors=_init_errors.get(idx),
    )

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

@router.get('/forecast', response_model=ForecastResponse)
async def forecast(
    background_tasks: BackgroundTasks,
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

    # Phase 14: Async Pre-fetch
    # If user requests horizon H, speculatively pre-fetch 2*H (up to max)
    next_horizon = horizon * 2
    if next_horizon <= 720:
        background_tasks.add_task(
            _prefetch_forecast,
            index=idx,
            horizon=next_horizon,
            quantiles=quantiles,
            underlying=underlying,
            avg_iv=avg_iv,
            minutes_to_expiry=minutes_to_expiry,
            recent_window_size=recent_window_size,
            detail=detail
        )

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
        cached = _FORECAST_CACHE.get(cache_key)
    if cached is not None:
        # Mark cache hit in metadata clone
        cached.metadata.cache_hit = True
        return cached
    try:
        # Phase 16: Non-blocking forecast execution
        times, qmap = await run_in_threadpool(
            fore.forecast_path,
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
    # Adaptive TTL preview (computed below) will be attached via dynamic attribute 'adaptive_ttl_sec'
    
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
    ttl_override = _FORECAST_CACHE.compute_adaptive_ttl(avg_iv, recent_window)
    if ttl_override is not None:
        try:
            setattr(resp.metadata, 'adaptive_ttl_sec', ttl_override)
            # Phase 12: Export adaptive TTL to Prometheus
            from ..prom_metrics import set_forecast_adaptive_ttl  # type: ignore
            set_forecast_adaptive_ttl(idx, horizon, float(ttl_override))
        except Exception:
            pass
    _FORECAST_CACHE.put(cache_key, resp, ttl_override=ttl_override)
    
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

    # Phase 13: Log Meta-Data for Learned Weighting
    try:
        from ..meta_collector import log_forecast_event  # type: ignore
        # Extract component predictions from last_meta if available
        comp_preds = {}
        if 'baseline_tp' in lm:
            comp_preds['baseline'] = float(lm['baseline_tp'])
        # TODO: Add GBRT/Retrieval p50s once exposed in last_meta
        
        log_forecast_event(
            index=idx,
            horizon=horizon,
            context=context,
            forecast_data=forecast_data,
            metadata={'weights': meta.weights, 'confidence': confidence},
            component_preds=comp_preds
        )
    except Exception:
        pass

    return resp

def _prefetch_forecast(
    index: str,
    horizon: int,
    quantiles: str,
    underlying: float,
    avg_iv: float,
    minutes_to_expiry: float,
    recent_window_size: int,
    detail: Optional[str]
):
    """Background task to pre-calculate forecast for a different horizon."""
    try:
        # Re-use the same logic as the main endpoint, but without returning response
        # Just populating the cache
        idx = index.upper().strip()
        fore = _get_forecaster(idx)
        if fore is None:
            return

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

        # Build minimal context
        now_ms = int(time.time() * 1000)
        context = {
            'index': idx,
            'now_ms': now_ms,
            'underlying': underlying,
            'avg_iv': avg_iv,
            'minutes_to_expiry': minutes_to_expiry,
            'live_rows': [],
        }

        recent_window = _load_recent_window(idx, recent_window_size)
        if recent_window is None:
            recent_window = []

        # Check cache first to avoid redundant work
        detail_normalized = detail.lower() if detail else ""
        avg_iv_bucket = _bucket_avg_iv(avg_iv)
        cache_key = (idx, horizon, quantiles, underlying, avg_iv_bucket, minutes_to_expiry, recent_window_size, detail_normalized)
        
        if _FORECAST_CACHE.get(cache_key) is not None:
            return

        # Compute
        times, qmap = fore.forecast_path(
            recent_window=recent_window,
            context=context,
            quantiles=q_list,
            horizon_minutes=horizon,
            bucket_ms=60_000,
        )
        
        if qmap is None:
            qmap = {}

        # Construct response object to cache it
        # (Simplified construction for cache population)
        def _first(q: float) -> float:
            seq = qmap.get(q, ())
            return float(seq[0]) if seq else 0.0

        lm = getattr(fore, 'last_meta', {}) or {}
        confidence = float(lm.get('confidence', 0.0))
        
        p10 = _first(0.1 if 0.1 in qmap else q_list[0])
        p50 = _first(0.5 if 0.5 in qmap else q_list[len(q_list)//2])
        p90 = _first(0.9 if 0.9 in qmap else q_list[-1])
        
        forecast_data = {'p10': p10, 'p50': p50, 'p90': p90}
        
        meta = ForecastMetadata(
            latency_ms=0.0, # Background task
            components_used=['background_prefetch'],
            weights={},
            recent_count=len(recent_window),
            cache_hit=False
        )
        
        # Handle detail mode
        time_grid_obj = None
        quantile_paths_obj = None
        if detail_normalized == 'full':
            time_grid_obj = TimeGrid(
                start=now_ms,
                end=now_ms + horizon * 60_000,
                resolution_ms=60_000,
                values=times
            )
            quantile_paths_obj = {}
            for q in q_list:
                label = _quantile_to_label(q)
                path = qmap.get(q, [])
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
        
        # Compute adaptive TTL
        ttl_override = _FORECAST_CACHE.compute_adaptive_ttl(avg_iv, recent_window)
        _FORECAST_CACHE.put(cache_key, resp, ttl_override=ttl_override)
        
        _LOG.info(f"Prefetched forecast for {idx} horizon={horizon}")
        
    except Exception as e:
        _LOG.warning(f"Prefetch failed: {e}")

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

# NOTE: Duplicate /regime/breaches definition removed later in file; this version kept for backward compatibility with
# existing flat-list consumers. Prefer the typed version (response_model=list[RegimeBreach]) below for new integrations.

# NOTE: /metrics/compare definition moved to end of file (consolidated).


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

@router.get('/regime/threshold_manifest')
async def regime_threshold_manifest(include_full: int = Query(1, ge=0, le=1, description="Include full manifest contents (0/1)")):
    """Return latest promoted drift threshold manifest (governance scheduler output).

    Response shape:
    {
      "status": "ok" | "missing",
      "latest_signature": <sha256 or null>,
      "manifest_file": "manifest_YYYYMMDD_HHMMSS.json",
      "promoted": true/false,
      "reason": "stable" | "unstable" | "guard_rails:...",
      "thresholds": { ... }  # only if include_full=1 and manifest present
    }
    """
    try:
        base_dir = Path('metrics') / 'drift_manifests'
        latest_ptr = base_dir / 'latest.json'
        if not latest_ptr.is_file():
            return {"status": "missing"}
        try:
            with open(latest_ptr, 'r', encoding='utf-8') as f:
                latest_meta = json.load(f)
        except Exception as e:
            _LOG.warning(f"threshold_manifest_latest_read_failed: {e}")
            raise HTTPException(status_code=500, detail="threshold_manifest_latest_read_failed")
        manifest_file = latest_meta.get('manifest_file')
        signature = latest_meta.get('signature')
        out = {
            "status": "ok",
            "latest_signature": signature,
            "manifest_file": manifest_file,
        }
        if include_full == 1 and manifest_file:
            mf_path = base_dir / manifest_file
            if mf_path.is_file():
                try:
                    with open(mf_path, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                    out.update({
                        "promoted": manifest.get("promoted"),
                        "reason": manifest.get("reason"),
                        "thresholds": manifest.get("thresholds", {}),
                        "horizons_used": manifest.get("horizons_used"),
                        "percentiles": manifest.get("percentiles"),
                        "stability": manifest.get("stability"),
                    })
                    # Augment with relative shift details if stability helpers available
                    if load_artifacts and compute_report:
                        try:
                            artifacts = load_artifacts(str(base_dir))
                            # Use horizons_used from manifest as min_horizons to mirror promotion constraints
                            min_h = int(out.get("horizons_used") or 1)
                            # max_percent_shift here unused (report already computed); pass large to avoid filtering
                            report = compute_report(artifacts, max_pct=10.0, min_horizons=min_h)
                            rel_keys = []
                            for entry in report.get("keys", []):
                                rel = entry.get("relative_shift")
                                if rel is None:
                                    continue
                                rel_keys.append({
                                    "key": entry.get("key"),
                                    "relative_shift": rel,
                                    "relative_shift_pct": round(rel * 100.0, 3),
                                    "violation": bool(entry.get("violation")),
                                })
                            if rel_keys:
                                out["relative_shifts"] = rel_keys
                        except Exception as e:  # pragma: no cover
                            _LOG.debug(f"threshold_manifest_shift_calc_failed: {e}")
                except Exception as e:
                    _LOG.warning(f"threshold_manifest_read_failed: {e}")
                    # keep minimal data; do not fail entire endpoint
        return out
    except HTTPException:
        raise
    except Exception as e:
        _LOG.warning(f"regime_threshold_manifest_failed: {e}")
        raise HTTPException(status_code=500, detail="regime_threshold_manifest_failed")

@router.get('/regime/threshold_manifest_history')
async def regime_threshold_manifest_history(limit: int = Query(50, ge=1, le=500, description="Max number of manifest entries to return")):
    """Return a chronological list (newest first) of recent drift threshold manifests.

    Each entry includes: ts_ms, promoted_at, promoted, reason, horizons_used, thresholds, signature.
    This supports Grafana Infinity panels for horizons_used trend and audit timelines.
    """
    try:
        base_dir = Path('metrics') / 'drift_manifests'
        if not base_dir.is_dir():
            return []
        manifests = []
        # Collect manifest_* files
        for f in sorted(base_dir.glob('manifest_*.json'), reverse=True):
            try:
                with open(f, 'r', encoding='utf-8') as _fh:
                    m = json.load(_fh)
                promoted_at = m.get('promoted_at')
                # Convert timestamp to epoch ms best-effort
                ts_ms = None
                if isinstance(promoted_at, str):
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(promoted_at.replace('Z','+00:00'))
                        ts_ms = int(dt.timestamp() * 1000)
                    except Exception:
                        pass
                manifests.append({
                    'file': f.name,
                    'promoted_at': promoted_at,
                    'ts_ms': ts_ms,
                    'promoted': m.get('promoted'),
                    'reason': m.get('reason'),
                    'horizons_used': m.get('horizons_used'),
                    'signature': m.get('signature'),
                    'thresholds': m.get('thresholds'),
                })
                if len(manifests) >= limit:
                    break
            except Exception:
                continue
        return manifests
    except Exception as e:
        _LOG.warning(f"regime_threshold_manifest_history_failed: {e}")
        raise HTTPException(status_code=500, detail="regime_threshold_manifest_history_failed")

@router.get('/regime/autotune_canary_history')
async def regime_autotune_canary_history(limit: int = Query(100, ge=1, le=1000, description="Max number of canary entries to return")):
    """Return recent auto-tune canary results from JSONL history (newest first)."""
    try:
        base_dir = Path('metrics') / 'drift_manifests'
        hist_file = base_dir / 'canary_history.jsonl'
        if not hist_file.is_file():
            return []
        lines = []
        with open(hist_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                lines.append(line)
        out = []
        for s in reversed(lines[-limit:]):
            try:
                out.append(json.loads(s))
            except Exception:
                continue
        return out
    except Exception as e:
        _LOG.warning(f"regime_autotune_canary_history_failed: {e}")
        raise HTTPException(status_code=500, detail="regime_autotune_canary_history_failed")

@router.get('/ttl_study')
async def ttl_study_latest():
    """Return latest TTL impact study JSON if present."""
    try:
        path = Path('metrics') / 'ttl_study' / 'latest.json'
        if not path.is_file():
            return {"available": False}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        _LOG.warning(f"ttl_study_latest_failed: {e}")
        raise HTTPException(status_code=500, detail="ttl_study_latest_failed")

@router.get('/feature_importance/latest')
async def feature_importance_latest(top_k: int = Query(15, ge=1, le=100)):
    """Return latest feature importance top-k from history file.

    Shape: { timestamp, top: [ {feature, importance}, ... ] }
    """
    hist = _read_fi_history()
    if not hist:
        return {"available": False}
    last = hist[-1]
    imp = last.get('importance') or {}
    items = sorted(imp.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return {
        "timestamp": last.get('timestamp'),
        "top": [{"feature": k, "importance": float(v)} for k, v in items]
    }

@router.get('/feature_importance/history')
async def feature_importance_history(limit: int = Query(200, ge=1, le=1000), top_k: int = Query(10, ge=1, le=50)):
    """Return flattened history entries for top-k features over last N records.

    Shape: [ {ts, feature, importance}, ... ] with ts in ms.
    Top-k selected from latest record.
    """
    hist = _read_fi_history()
    if not hist:
        return []
    window = hist[-limit:]
    latest_imp = (hist[-1].get('importance') or {}) if hist else {}
    top_feats = [k for k, _v in sorted(latest_imp.items(), key=lambda x: x[1], reverse=True)[:top_k]]
    out: list[dict[str, Any]] = []
    for rec in window:
        ts_iso = rec.get('timestamp')
        try:
            ts_ms = int(datetime.fromisoformat(ts_iso.replace('Z','')).timestamp() * 1000) if ts_iso else None
        except Exception:
            ts_ms = None
        imp = rec.get('importance') or {}
        for f in top_feats:
            out.append({
                'ts': ts_ms,
                'feature': f,
                'importance': float(imp.get(f, 0.0))
            })
    return out

@router.get('/feature_importance/timeseries')
async def feature_importance_timeseries(limit: int = Query(200, ge=1, le=1000), top_k: int = Query(10, ge=1, le=50)):
    """Return wide timeseries for top-k features: [{ts, f1, f2, ...}].

    Feature set chosen from latest record top-k.
    """
    hist = _read_fi_history()
    if not hist:
        return []
    window = hist[-limit:]
    latest_imp = (hist[-1].get('importance') or {}) if hist else {}
    top_feats = [k for k, _v in sorted(latest_imp.items(), key=lambda x: x[1], reverse=True)[:top_k]]
    out: list[dict[str, Any]] = []
    for rec in window:
        ts_iso = rec.get('timestamp')
        try:
            ts_ms = int(datetime.fromisoformat(ts_iso.replace('Z','')).timestamp() * 1000) if ts_iso else None
        except Exception:
            ts_ms = None
        row: dict[str, Any] = {'ts': ts_ms}
        imp = rec.get('importance') or {}
        for f in top_feats:
            row[f] = float(imp.get(f, 0.0))
        out.append(row)
    return out

@router.get('/feature_shift/latest')
async def feature_shift_latest():
    """Return latest feature shift (PSI/KS) payload written by compute_feature_shift script."""
    path = Path('metrics') / 'feature_shift' / 'latest.json'
    if not path.is_file():
        return {"available": False}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        raise HTTPException(status_code=500, detail='feature_shift_latest_read_failed')

@router.get('/feature_shift/history')
async def feature_shift_history(limit: int = Query(100, ge=1, le=1000), index: Optional[str] = Query(None)):
    """Return last N historical feature shift entries from JSONL file."""
    hist_file = Path('metrics') / 'feature_shift' / 'history.jsonl'
    if not hist_file.is_file():
        return []
    out: list[dict[str, Any]] = []
    index_set: Optional[set[str]] = None
    if index:
        index_set = {s.strip().upper() for s in index.split(',') if s.strip()}
    try:
        lines = hist_file.read_text(encoding='utf-8').strip().splitlines()
        for line in lines[-limit:]:
            try:
                rec = json.loads(line)
                if index_set:
                    rec_idx = str(rec.get('index', '')).upper()
                    if rec_idx not in index_set:
                        continue
                out.append(rec)
            except Exception:
                continue
    except Exception:
        return []
    return out

@router.get('/feature_shift/heatmap')
async def feature_shift_heatmap(metric: str = Query("psi", pattern="^(psi|ks)$"), limit: int = Query(200, ge=1, le=2000), index: Optional[str] = Query(None)):
    """Return flattened rows suitable for heatmap/state timeline: [{ts, feature, value, index}].

    Uses ts_ms if available in history lines; otherwise attempts to parse generated_at; entries without time are skipped.
    """
    hist_file = Path('metrics') / 'feature_shift' / 'history.jsonl'
    if not hist_file.is_file():
        return []
    rows: list[dict[str, Any]] = []
    index_set: Optional[set[str]] = None
    if index:
        index_set = {s.strip().upper() for s in index.split(',') if s.strip()}
    try:
        lines = hist_file.read_text(encoding='utf-8').strip().splitlines()
        for line in lines[-limit:]:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ts_ms = rec.get('ts_ms')
            if not ts_ms:
                ts_iso = rec.get('generated_at')
                if ts_iso:
                    try:
                        ts_ms = int(datetime.fromisoformat(ts_iso.replace('Z','+00:00')).timestamp() * 1000)
                    except Exception:
                        ts_ms = None
            if ts_ms is None:
                continue
            idx = rec.get('index')
            if index_set and str(idx).upper() not in index_set:
                continue
            feats = rec.get('features') or []
            for f in feats:
                name = f.get('feature')
                val = f.get(metric)
                if name is None or val is None:
                    continue
                rows.append({'ts': ts_ms, 'feature': name, 'value': float(val), 'index': idx})
    except Exception:
        return []
    return rows

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
    
    If include_drift=1:
    - Adds feature drift summary (PSI/KS) if index provided.
    - Adds performance drift summary (MAE/Norm ratios) if index AND horizon provided.
    - Exports performance drift metrics to Prometheus if index AND horizon provided.
    """
    try:
        from ..rolling_mae import ensure_started, get_metric_comparison  # type: ignore
        ensure_started()
        result = get_metric_comparison(index=index, horizon=horizon)
        
        if include_drift == 1 and index:
            # 1. Feature Drift (PSI/KS)
            try:
                from ..drift_metrics import get_drift_summary as get_feature_drift_summary  # type: ignore
                drift_feat = get_feature_drift_summary(index=index)
                if isinstance(result, dict):
                    result["drift_summary"] = drift_feat
            except Exception:
                pass

            # 2. Performance Drift (MAE/Norm Ratios) - requires horizon
            if horizon:
                try:
                    from ..rolling_mae import get_drift_summary as get_perf_drift_summary  # type: ignore
                    drift_perf = get_perf_drift_summary(index.upper(), horizon)
                    
                    # Merge into drift_summary
                    if isinstance(result, dict):
                        if "drift_summary" not in result:
                            result["drift_summary"] = {}
                        if isinstance(result["drift_summary"], dict):
                            result["drift_summary"].update(drift_perf)

                    # Export to Prometheus (Side Effect)
                    from ..prom_metrics import set_forecast_drift_ratios, set_forecast_coverage_drift  # type: ignore
                    set_forecast_drift_ratios(index.upper(), horizon, float(drift_perf.get('mae_ratio',0.0)), float(drift_perf.get('norm_ratio',0.0)))
                    set_forecast_coverage_drift(index.upper(), horizon, float(drift_perf.get('coverage_delta_pct',0.0)))
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
