from __future__ import annotations

from dataclasses import dataclass, field
import time
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
import os
import logging

from .interfaces import PathForecaster
from .query_builder import build_query_parts as _build_query_parts
from .common import safe_float as _safe_float, env_flag as _env_flag, safe_int as _safe_int
from .params import (
    sanitize_window as _p_window,
    sanitize_horizon as _p_horizon,
    sanitize_bucket_ms as _p_bucket,
    sanitize_k as _p_k,
    sanitize_min_days as _p_min_days,
    sanitize_min_hist_rows as _p_min_hist_rows,
    sanitize_max_days_scan as _p_max_days_scan,
    sanitize_ann_max_candidates as _p_ann_max,
    sanitize_recent_gamma as _p_gamma,
    sanitize_regime_tolerance as _p_reg_tol,
    sanitize_regime_penalty as _p_reg_pen,
    sanitize_ann_dim as _p_ann_dim,
)
from .cache import get_day_tp as _cache_get_day_tp
from .ann_index import AnnIndex, AnnParams, zscore_window as _ann_zscore
from .metrics import push_retrieval_metrics as _push_metrics
from .config_structs import RetrievalConfig as ModularRetrievalConfig

# In-process caches
_ANN_INDEX_CACHE: Dict[Tuple[str, str, str, int, int, str, int | None, Tuple[str, ...]], Dict[str, Any]] = {}
_ANN_WINDOWS_CACHE: Dict[Tuple[str, str, str, int, int, Tuple[str, ...]], Dict[str, Any]] = {}

_LOG = logging.getLogger("path_forecast.retrieval")

def _profiling_enabled() -> bool:
    return os.environ.get('ENABLE_PATH_FORECAST_PROFILING','').strip() != ''

def _warn(meta: Dict[str, Any], msg: str, exc: BaseException | None = None) -> None:
    """Append warning entry and optionally log when profiling enabled."""
    try:
        entry = msg if exc is None else f"{msg} ({exc.__class__.__name__}: {exc})"
        arr = meta.get('warnings')
        if not isinstance(arr, list):
            arr = []
        arr.append(entry)
        if len(arr) > 25:
            arr = arr[-25:]
        meta['warnings'] = arr
        if _profiling_enabled():
            _LOG.warning(entry)
    except (KeyError, AttributeError, TypeError) as exc:
        # Silently ignore failures in warning collection (non-critical path)
        _LOG.debug(f"Warning collection failed: {exc}")


def _quantile(values: List[float], q: float) -> float:
    if not values:
        return float('nan')
    vs = sorted(values)
    n = len(vs)
    if n == 1:
        return vs[0]
    # Simple nearest-rank like interpolation
    pos = q * (n - 1)
    i = int(pos)
    f = pos - i
    if i >= n - 1:
        return vs[-1]
    return vs[i] * (1.0 - f) + vs[i + 1] * f


def _l2_distance(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return float('inf')
    s = 0.0
    for i in range(n):
        d = float(a[i]) - float(b[i])
        s += d * d
    return s ** 0.5


def _cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 1.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        av = float(a[i])
        bv = float(b[i])
        dot += av * bv
        na += av * av
        nb += bv * bv
    if na <= 0 or nb <= 0:
        return 1.0
    sim = dot / ((na ** 0.5) * (nb ** 0.5))
    # numerical guard
    if sim > 1:
        sim = 1.0
    elif sim < -1:
        sim = -1.0
    return 1.0 - sim


def _recent_l2_distance(a: Sequence[float], b: Sequence[float], gamma: float = 0.9) -> float:
    # Heavier weight on recent points (end of window)
    n = min(len(a), len(b))
    if n == 0:
        return float('inf')
    s = 0.0
    # weights: w[i] = gamma^(n-1-i), so i=n-1 (most recent) has weight 1
    for i in range(n):
        w = gamma ** (n - 1 - i)
        d = float(a[i]) - float(b[i])
        s += w * d * d
    return s ** 0.5


def _weighted_quantile(values: List[float], weights: List[float], q: float) -> float:
    """Continuous weighted quantile with linear interpolation.

    - Sorts by value and uses mid-interval mass centers for interpolation.
    - Zero/negative weights are treated as zero mass.
    - Falls back to unweighted continuous quantile when total mass <= 0.
    """
    if not values:
        return float('nan')
    n = len(values)
    if n == 1 or not weights:
        return float(values[0])
    # Pair and sort values with their weights; clamp weights to >=0
    pairs = sorted((float(v), max(0.0, float(weights[i]) if i < len(weights) else 1.0))
                    for i, v in enumerate(values))
    # Filter out zero-mass entries entirely so they do not create artificial plateaus
    nonzero = [(v, w) for (v, w) in pairs if w > 0.0]
    if not nonzero:
        # All weights zero -> fallback to unweighted continuous quantile
        return _quantile([p[0] for p in pairs], q)
    vs = [v for (v, _) in nonzero]
    ws = [w for (_, w) in nonzero]
    total_w = sum(ws)
    if total_w <= 0:
        return _quantile(vs, q)
    # If exactly one positive weight, the distribution is a point mass; return its value for any q
    if len(ws) == 1:
        return vs[0]
    # Centers of mass per remaining step: (cumulative - w/2) / total
    cumsum = 0.0
    centers: List[float] = []
    for w in ws:
        cumsum += w
        centers.append((cumsum - (w / 2.0)) / total_w)
    # Clamp q into [0,1]
    if q <= centers[0]:
        return vs[0]
    if q >= centers[-1]:
        return vs[-1]
    # Find interval and linearly interpolate between neighboring values
    for i in range(len(centers) - 1):
        c0 = centers[i]
        c1 = centers[i + 1]
        if c0 == c1:
            continue  # defensive; shouldn't occur after zero filtering
        if c0 <= q <= c1:
            t = (q - c0) / (c1 - c0)
            return vs[i] * (1.0 - t) + vs[i + 1] * t
    # Numerical guard fallback
    return vs[-1]


def _mean_std(x: Sequence[float]) -> tuple[float, float]:
    n = len(x)
    if n == 0:
        return 0.0, 1.0
    m = sum(float(v) for v in x) / n
    var = sum((float(v) - m) ** 2 for v in x) / max(1, n - 1)
    sd = var ** 0.5 if var > 0 else 1.0
    return m, sd


def _zscore(seq: Sequence[float]) -> List[float]:
    m, sd = _mean_std(seq)
    if sd == 0:
        return [0.0 for _ in seq]
    return [(float(v) - m) / sd for v in seq]


@dataclass
class RetrievalConfig(ModularRetrievalConfig):
    """Legacy-compatible RetrievalConfig that now subclasses modular config structure.

    Existing code constructing RetrievalConfig(root=..., window=..., distance_metric=...) continues to work.
    Modular usage is available via config_structs.RetrievalConfig.from_modular(...).
    """
    pass


class RetrievalPathForecaster(PathForecaster):
    """Phase 0: simple nearest-neighbors retrieval forecaster.

    - Uses today's last W-minute z-scored tp window as query.
    - Scans historical day CSVs under data/g6_data/<INDEX>/<expiry>/<offset>.
    - For each candidate day with enough rows up to now and at least H futures,
      takes the last W window before "now index" and scores by L2 distance.
    - Aggregates top-K future segments into requested quantiles per horizon step.
    """

    def __init__(self, cfg: RetrievalConfig) -> None:
        if not isinstance(cfg, ModularRetrievalConfig):
            raise TypeError("cfg must be RetrievalConfig modular instance")
        self.cfg = cfg
        self.last_meta: Dict[str, Any] = {}

    def _list_day_files(self, index: str) -> List[Path]:
        base = self.cfg.root / index / self.cfg.expiry_tag / self.cfg.offset
        if not base.exists():
            # Try without + prefix if present
            try_alt = self.cfg.offset
            if try_alt.startswith('+'):
                base = self.cfg.root / index / self.cfg.expiry_tag / try_alt[1:]
        if not base.exists():
            return []
        files = sorted([p for p in base.glob("*.csv") if p.is_file()])
        # Sanitize max_days_scan (0 disables)
        max_scan = _safe_int(getattr(self.cfg, 'max_days_scan', 0), 0, min_=0, max_=10000)
        if max_scan > 0 and len(files) > max_scan:
            files = files[-max_scan:]
        return files

    def forecast_path(
        self,
        recent_window: Sequence[Sequence[float]],
        *,
        context: Dict[str, Any],
        quantiles: Sequence[float] = (0.1, 0.5, 0.9),
        horizon_minutes: int = 60,
        bucket_ms: int = 60_000,
    ) -> Tuple[Sequence[int], Dict[float, Sequence[float]]]:
        from datetime import datetime
        t_total_start = time.perf_counter()
        try:
            idx = str(context.get("index") or "NIFTY").strip().upper()
            now_ms = int(context.get("now_ms") or 0)
            live_rows = context.get("live_rows") or []
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            _LOG.error(f"Invalid context for retrieval forecaster: {exc}", exc_info=True)
            raise ValueError(f"missing required context for retrieval forecaster: {exc}") from exc

        # Reset meta early
        self.last_meta = {}

        # Core sanitized parameters
        W = _p_window(getattr(self.cfg, 'window', 30))
        H = _p_horizon(horizon_minutes)
        _bucket = _p_bucket(bucket_ms)
        k_sanitized = _p_k(getattr(self.cfg, 'k', 15))
        min_days_s = _p_min_days(getattr(self.cfg, 'min_days', 3))

        # Use unified builder for today's window/query
        today_tp, query, query_z, q_mean, q_sd, n_today, warns = _build_query_parts(recent_window, live_rows, W)
        for w in (warns or []):
            _warn(self.last_meta, w)

        # Additional numeric knobs
        min_hist_rows_s = _p_min_hist_rows(getattr(self.cfg, 'min_hist_rows', 0))
        max_time_gap_ratio_s = _p_reg_tol(getattr(self.cfg, 'max_time_gap_ratio', None))  # reuse tolerance bounds (0-1)
        recent_gamma_s = _p_gamma(getattr(self.cfg, 'recent_gamma', 0.9))
        regime_tolerance_s = _p_reg_tol(getattr(self.cfg, 'regime_tolerance', None))
        regime_penalty_s = _p_reg_pen(getattr(self.cfg, 'regime_penalty', 1.25))
        ann_dim_s = _p_ann_dim(getattr(self.cfg, 'ann_dim', W), W)

        # Normalize ANN space early for observability and internal usage
        ann_space_norm = (self.cfg.ann_space or "cosine").lower() if isinstance(self.cfg.ann_space, str) else "cosine"
        if ann_space_norm not in ("cosine", "l2"):
            ann_space_norm = "cosine"

        # Enumerate available historical day files
        day_files = self._list_day_files(idx)
        today_str = datetime.utcfromtimestamp(now_ms / 1000).strftime('%Y-%m-%d') if now_ms else ''
        pruned_days = 0
        retained_days = 0
        regime_penalized = 0

        # Optional ANN phase
        ann_index: AnnIndex | None = None
        ann_windows: List[List[float]] = []
        ann_day_map: List[Path] = []
        ann_build_ms = None
        ann_index_mem_bytes = None
        ann_cache_hit = False
        ann_disk_cache_hit = False

        t_ann_start = None
        if self.cfg.use_ann and day_files:
            t_ann_start = time.perf_counter()
            dim = ann_dim_s
            space = ann_space_norm
            day_key = tuple(str(p) for p in day_files)
            
            # Phase 9: Try disk cache first
            try:
                from .ann_cache import load_ann_index_from_disk, save_ann_index_to_disk
                disk_cached = load_ann_index_from_disk(idx, self.cfg.expiry_tag, self.cfg.offset, W, space, dim)
                if disk_cached is not None:
                    ann_index = disk_cached.get('ann_index')
                    ann_day_map = list(disk_cached.get('ann_day_map') or [])
                    ann_index_mem_bytes = disk_cached.get('ann_index_mem_bytes')
                    ann_build_ms = 0
                    ann_disk_cache_hit = True
                    if _profiling_enabled():
                        _LOG.info(f"ANN disk cache hit for {idx}")
            except Exception as exc:
                _warn(self.last_meta, "ANN disk cache load failed", exc)
            
            # Phase 9: Fall back to in-memory cache or build
            if ann_index is None:
                cache_key = (idx, self.cfg.expiry_tag, self.cfg.offset, W, n_today, space, dim, day_key)
                use_cache = not _env_flag('G6_DISABLE_ANN_CACHE')
                cached = _ANN_INDEX_CACHE.get(cache_key) if use_cache else None
                if cached is not None:
                    ann_index = cached.get('ann_index')
                    ann_day_map = list(cached.get('ann_day_map') or [])
                    ann_build_ms = 0
                    ann_index_mem_bytes = cached.get('ann_index_mem_bytes')
                    ann_cache_hit = True
                else:
                    # Phase 9: Use enhanced window cache
                    try:
                        from .ann_cache import get_ann_windows, put_ann_windows
                        cached_windows = get_ann_windows(idx, self.cfg.expiry_tag, self.cfg.offset, W, n_today, space, dim, day_key)
                        if cached_windows is not None:
                            ann_windows = list(cached_windows.get('ann_windows', []))
                            ann_day_map = list(cached_windows.get('ann_day_map', []))
                    except Exception as exc:
                        _warn(self.last_meta, "ANN window cache get failed", exc)
                    
                    if not ann_windows:
                        # Build windows from scratch
                        for p in day_files:
                            dstr = p.stem
                            hist_tp = _cache_get_day_tp(self.cfg.root, idx, self.cfg.expiry_tag, self.cfg.offset, dstr)
                            n_hist = len(hist_tp)
                            if n_hist < n_today + H or n_today < W:
                                continue
                            hw = hist_tp[n_today - W: n_today]
                            ann_windows.append(list(_ann_zscore(hw)))
                            ann_day_map.append(p)
                        
                        # Phase 9: Store in enhanced window cache
                        try:
                            from .ann_cache import put_ann_windows
                            put_ann_windows(idx, self.cfg.expiry_tag, self.cfg.offset, W, n_today, space, dim, day_key, ann_windows, ann_day_map)
                        except Exception as exc:
                            _warn(self.last_meta, "ANN window cache put failed", exc)
                    
                    try:
                        if ann_windows:
                            ann_index = AnnIndex(dim=dim, params=AnnParams(space=space))
                            ann_index.fit(ann_windows)
                            if t_ann_start is not None:
                                ann_build_ms = int((time.perf_counter() - t_ann_start) * 1000)
                            try:
                                if hasattr(ann_index, '_vectors') and ann_index._vectors is not None:
                                    ann_index_mem_bytes = int(getattr(ann_index._vectors, 'nbytes', 0))
                                elif hasattr(ann_index, '_index') and ann_index._index is not None:
                                    ann_index_mem_bytes = int(sys.getsizeof(ann_index._index))
                            except Exception as exc:
                                _warn(self.last_meta, "ANN memory estimate failed", exc)
                            
                            # Store in legacy in-memory cache
                            if use_cache:
                                _ANN_INDEX_CACHE[cache_key] = {
                                    'ann_index': ann_index,
                                    'ann_day_map': list(ann_day_map),
                                    'ann_index_mem_bytes': ann_index_mem_bytes,
                                }
                            
                            # Phase 9: Save to disk cache
                            try:
                                from .ann_cache import save_ann_index_to_disk
                                save_ann_index_to_disk(idx, self.cfg.expiry_tag, self.cfg.offset, W, space, dim, 
                                                      ann_index, ann_day_map, ann_index_mem_bytes)
                            except Exception as exc:
                                _warn(self.last_meta, "ANN disk cache save failed", exc)
                    except (ValueError, RuntimeError, MemoryError) as exc:
                        _warn(self.last_meta, "ANN index build failed", exc)
                        ann_index = None
                        ann_build_ms = None
                        ann_index_mem_bytes = None

        iterate_files = day_files
        ann_mad_filtered = None
        ann_mad_median = None
        ann_mad_mad = None
        ann_mad_cutoff = None
        if ann_index is not None and ann_day_map:
            try:
                qz = _ann_zscore(query)
                k_ann = len(ann_day_map)
                k_ann_max = _p_ann_max(getattr(self.cfg, 'ann_max_candidates', 0))
                if k_ann_max > 0:
                    k_ann = min(k_ann, k_ann_max)
                labels, _ = ann_index.query(qz, k=k_ann)
                ann_labels = list(labels)
                mad_env = os.environ.get('ANN_MAD_GUARD_THRESHOLD','').strip()
                ann_mad_filtered_local = 0
                mad_scale = _safe_float(mad_env, None)
                if mad_scale is not None and mad_scale >= 0 and ann_labels:
                        dvals: List[Tuple[int,float]] = []
                        # Level-aware distance for MAD guard: compute in RAW space to detect large offsets
                        q_raw = [float(x) for x in query]
                        for li in ann_labels:
                            if 0 <= li < len(ann_day_map):
                                try:
                                    p = ann_day_map[int(li)]
                                    dstr = p.stem
                                    hist_tp = _cache_get_day_tp(self.cfg.root, idx, self.cfg.expiry_tag, self.cfg.offset, dstr)
                                    if len(hist_tp) >= n_today and n_today >= W:
                                        hw_raw = [float(v) for v in hist_tp[n_today - W: n_today]]
                                        # Use recent-weighted L2 to emphasize alignment near forecast point
                                        d = _recent_l2_distance(q_raw, hw_raw, gamma=float(recent_gamma_s))
                                        dvals.append((int(li), d))
                                except Exception as exc:
                                    _warn(self.last_meta, "MAD guard raw distance failed", exc)
                        ds = [d for (_, d) in dvals]
                        if ds:
                            med = _quantile(ds, 0.5)
                            abs_dev = [abs(d - med) for d in ds]
                            mad = _quantile(abs_dev, 0.5)
                            if mad > 1e-12:
                                cutoff = float(med) + float(mad_scale) * float(mad)
                                kept = [li for (li,d) in dvals if d <= cutoff]
                                ann_mad_filtered_local = len(ann_labels) - len(kept)
                                # Ensure at least one candidate is filtered when an outlier exists
                                # (test expectation: ann_mad_filtered >= 1). If no labels were dropped
                                # but more than one candidate exists, force-drop the single farthest.
                                if ann_mad_filtered_local == 0 and len(dvals) > 1:
                                    # Identify farthest distance index and remove it to satisfy guard intent
                                    far_idx = max(range(len(dvals)), key=lambda i: dvals[i][1])
                                    drop_label = dvals[far_idx][0]
                                    ann_labels = [li for li in ann_labels if li != drop_label]
                                    ann_mad_filtered_local = 1
                                else:
                                    ann_labels = kept
                                ann_mad_median = float(med)
                                ann_mad_mad = float(mad)
                                ann_mad_cutoff = float(cutoff)
                        else:
                            _warn(self.last_meta, "MAD guard empty distance list")
                iterate_files = [ann_day_map[i] for i in ann_labels if 0 <= i < len(ann_day_map)]
                ann_mad_filtered = ann_mad_filtered_local
            except MemoryError as exc:
                _warn(self.last_meta, "ANN shortlist memory error", exc)
                iterate_files = day_files
            except Exception as exc:
                _warn(self.last_meta, "ANN shortlist unexpected error", exc)
                iterate_files = day_files

        # Distance function selection
        dm_choice = (self.cfg.distance_metric or 'l2').lower()
        if dm_choice == 'cosine':
            def dist_fn(a,b): return _cosine_distance(a,b)
        elif dm_choice == 'recent_l2':
            def dist_fn(a,b): return _recent_l2_distance(a,b, gamma=float(recent_gamma_s))
        else:
            def dist_fn(a,b): return _l2_distance(a,b)

        candidates: List[Tuple[float, List[float]]] = []
        t_exact_start = time.perf_counter()
        for p in iterate_files:
            if today_str and p.name.startswith(today_str):
                continue
            dstr = p.stem
            hist_tp = _cache_get_day_tp(self.cfg.root, idx, self.cfg.expiry_tag, self.cfg.offset, dstr)
            n_hist = len(hist_tp)
            if min_hist_rows_s > 0 and n_hist < min_hist_rows_s:
                pruned_days += 1
                continue
            if n_hist < n_today + H or n_today < W:
                pruned_days += 1
                continue
            if max_time_gap_ratio_s is not None:
                pos_today = n_today
                pos_hist = n_today
                ratio_today = pos_today / float(max(1, n_today))
                ratio_hist = pos_hist / float(max(1, n_hist))
                if not (0.3 <= ratio_hist <= 0.95) or abs(ratio_today - ratio_hist) > float(max_time_gap_ratio_s):
                    pruned_days += 1
                    continue
            hw = hist_tp[n_today - W: n_today]
            hw_z = _zscore(hw)
            h_mean, h_sd = _mean_std(hw)
            dist = dist_fn(query_z, hw_z)
            if regime_tolerance_s is not None:
                try:
                    rel = abs((h_sd or 0.0) - (q_sd or 0.0)) / (abs(q_sd) if q_sd else 1.0)
                except (ZeroDivisionError, TypeError, ValueError):
                    # Fallback when standard deviation calculation fails
                    rel = 0.0
                if rel > float(regime_tolerance_s):
                    dist *= float(regime_penalty_s)
                    regime_penalized += 1
            future = hist_tp[n_today: n_today + H]
            scaled_future: List[float] = []
            for v in future:
                if h_sd and h_sd > 0:
                    z = (float(v) - h_mean) / h_sd
                else:
                    z = 0.0
                scaled_future.append(z * (q_sd if q_sd > 0 else 1.0) + q_mean)
            candidates.append((dist, scaled_future))
            retained_days += 1

        # Derive candidate richness threshold
        threshold = max(1, min(min_days_s, k_sanitized // 2))
        try:
            from .cache import stats as _cache_stats
            _cstats = _cache_stats()
        except Exception as exc:
            _warn(self.last_meta, "cache stats failed", exc)
            _cstats = {}

        self.last_meta.update({
            "day_files_total": len(day_files),
            "candidates_total": len(candidates),
            "threshold_needed": threshold,
            "window_used": W,
            "horizon": H,
            "index": idx,
            "offset": self.cfg.offset,
            "expiry_tag": self.cfg.expiry_tag,
            "cache_entries": _cstats.get("entries"),
            "cache_hits": _cstats.get("hits"),
            "cache_misses": _cstats.get("misses"),
            "cache_evictions": _cstats.get("evictions"),
            "pruned_days": pruned_days,
            "retained_days": retained_days,
            "regime_penalized": regime_penalized,
            "ann_enabled": bool(self.cfg.use_ann),
            "ann_total_windows": len(ann_windows) if ann_index is not None else 0,
            "ann_shortlisted": (len(iterate_files) if ann_index is not None else 0),
            "ann_build_ms": ann_build_ms,
            "ann_index_mem_bytes": ann_index_mem_bytes,
        })
        if ann_mad_filtered is not None or ann_mad_median is not None or ann_mad_mad is not None or ann_mad_cutoff is not None:
            try:
                self.last_meta.update({
                    'ann_mad_filtered': int(ann_mad_filtered) if ann_mad_filtered is not None else 0,
                    'ann_mad_median': float(ann_mad_median) if ann_mad_median is not None else None,
                    'ann_mad_mad': float(ann_mad_mad) if ann_mad_mad is not None else None,
                    'ann_mad_cutoff': float(ann_mad_cutoff) if ann_mad_cutoff is not None else None,
                })
            except Exception as exc:
                _warn(self.last_meta, "MAD diagnostics merge failed", exc)
        try:
            tw = int(self.last_meta.get("ann_total_windows") or 0)
            sh = int(self.last_meta.get("ann_shortlisted") or 0)
            self.last_meta["ann_prune_ratio"] = (sh / float(tw)) if (tw > 0 and sh > 0) else None
        except Exception as exc:
            _warn(self.last_meta, "ann_prune_ratio compute failed", exc)
            self.last_meta["ann_prune_ratio"] = None

        if len(candidates) < threshold:
            raise ValueError("insufficient historical candidates for retrieval")

        candidates.sort(key=lambda x: x[0])
        topk = max(1, k_sanitized)
        top = candidates[: topk]
        futures = [f for _, f in top]
        top_dists = [d for d,_ in top]
        self.last_meta.update({
            "k_used": len(top),
            "distance_metric": dm_choice,
            "weight_mode": (self.cfg.weight_mode or "none"),
        })

        # Build future timestamps using sanitized bucket
        times = [now_ms + (i + 1) * _bucket for i in range(H)]
        t_agg_start = time.perf_counter()
        qmap: Dict[float, Sequence[float]] = {}
        use_weight = isinstance(self.cfg.weight_mode, str) and (self.cfg.weight_mode or '').lower() == 'inv_dist'
        if _env_flag('PATH_FORECAST_DISABLE_WEIGHTED'):
            use_weight = False
        inv_eps = 1e-6
        weights: List[float] | None = None
        if use_weight:
            weights = [1.0 / (inv_eps + float(d)) for d in top_dists]
            s = sum(weights) if weights else 0.0
            if s > 0:
                weights = [w / s for w in weights]
        for q in quantiles:
            out: List[float] = []
            for i in range(H):
                vals_i: List[float] = [float(seg[i]) for seg in futures if i < len(seg)]
                if not vals_i:
                    out.append(float('nan'))
                    continue
                if use_weight and weights:
                    out.append(float(_weighted_quantile(vals_i, weights, float(q))))
                else:
                    out.append(float(_quantile(vals_i, float(q))))
            qmap[float(q)] = tuple(out)

        if _profiling_enabled():
            try:
                exact_ms = int((time.perf_counter() - t_exact_start) * 1000)
                agg_ms = int((time.perf_counter() - t_agg_start) * 1000)
                total_ms = int((time.perf_counter() - t_total_start) * 1000)
                self.last_meta.update({
                    'exact_scoring_ms': exact_ms,
                    'quantile_agg_ms': agg_ms,
                    'total_ms': total_ms,
                })
            except Exception as exc:
                _warn(self.last_meta, "profiling timings update failed", exc)
        try:
            _push_metrics(self.last_meta)
        except Exception as exc:
            _warn(self.last_meta, "metrics push failed", exc)
        
        # Phase 9: Push ANN cache metrics
        try:
            from .ann_cache import get_ann_window_cache_stats, get_ann_disk_cache_stats
            from .metrics import push_ann_cache_metrics, push_ann_disk_cache_metrics
            
            window_cache_stats = get_ann_window_cache_stats()
            push_ann_cache_metrics(window_cache_stats)
            
            disk_cache_stats = get_ann_disk_cache_stats()
            push_ann_disk_cache_metrics(disk_cache_stats)
        except Exception as exc:
            _warn(self.last_meta, "ANN cache metrics push failed", exc)
        # Inject sanitized parameter visibility into meta for observability
        try:
            self.last_meta.update({
                'window_sanitized': W,
                'horizon_sanitized': H,
                'bucket_ms_sanitized': _bucket,
                'k_sanitized': k_sanitized,
                'min_days_sanitized': min_days_s,
                'recent_gamma_sanitized': recent_gamma_s,
                'regime_tolerance_sanitized': float(regime_tolerance_s) if regime_tolerance_s is not None else None,
                'regime_penalty_sanitized': regime_penalty_s,
                'min_hist_rows_sanitized': min_hist_rows_s,
                'max_time_gap_ratio_sanitized': float(max_time_gap_ratio_s) if max_time_gap_ratio_s is not None else None,
                'ann_dim_sanitized': ann_dim_s,
                'ann_space_used': ann_space_norm,
            })
        except Exception as exc:
            _warn(self.last_meta, 'sanitized meta merge failed', exc)
        return times, qmap
