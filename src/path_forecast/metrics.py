"""Path forecast metrics utilities and optional Prometheus exposure.

Existing function:
- compute_ann_effectiveness: composite score combining speedup, pruning gain, and q50 MAD tolerance penalty.

New (guarded) Prometheus helpers (enabled when ENABLE_PATH_FORECAST_PROM_METRICS is set):
- push_retrieval_metrics(last_meta)
    Exposes histogram and gauges for latency, candidates, ANN stats, and stage timings.

Phase 9 additions:
- ANN cache metrics (hit ratio, size, evictions)
- ANN disk cache metrics (hits, load time)
- Stage-level latency histograms
"""
from __future__ import annotations

from typing import Optional, Any, cast
import os
import logging

from src.metrics.protocols import GaugeLike, HistogramLike

_LOG = logging.getLogger("path_forecast.metrics")

_REG: Any | None = None
_M_LATENCY: HistogramLike | None = None
_G_CANDIDATES: GaugeLike | None = None
_G_ANN_PRUNE_RATIO: GaugeLike | None = None
_G_ANN_BUILD_MS: GaugeLike | None = None
_G_EXACT_MS: GaugeLike | None = None
_G_AGG_MS: GaugeLike | None = None
_G_WINDOW_SAN: GaugeLike | None = None
_G_HORIZ_SAN: GaugeLike | None = None
_M_ALPHA_HIST: HistogramLike | None = None
_M_CANDIDATE_RICHNESS: HistogramLike | None = None

# Composite metrics
_M_COMP_LATENCY: HistogramLike | None = None
_G_COMP_PRIOR_CACHE_HIT: GaugeLike | None = None
_G_COMP_ALPHA: GaugeLike | None = None
_G_COMP_PRIOR_DAYS: GaugeLike | None = None
_G_COMP_RET_DAYS: GaugeLike | None = None

# Phase 9: ANN cache metrics
_G_ANN_CACHE_HIT_RATIO: GaugeLike | None = None
_G_ANN_CACHE_SIZE: GaugeLike | None = None
_G_ANN_CACHE_EVICTIONS: GaugeLike | None = None
_G_ANN_DISK_CACHE_HITS: GaugeLike | None = None
_G_ANN_DISK_CACHE_LOAD_MS: HistogramLike | None = None

# Phase 9: Stage-level latency histograms
_M_STAGE_LATENCY: dict[str, HistogramLike] = {}

_DEF_BUCKETS = [
    1, 2.5, 5, 7.5, 10, 15, 25, 50, 75, 100, 150, 250, 500, 750, 1000,
    1500, 2000, 3000, 5000
]


def _get_reg():
    """Initialize metrics once using default Prometheus registry.

    Returns a truthy value when metrics are enabled and initialized; None otherwise.
    """
    global _REG
    if _REG is not None:
        return _REG
    if os.environ.get("ENABLE_PATH_FORECAST_PROM_METRICS", "").strip() == "":
        return None
    try:
        from prometheus_client import Histogram as _H  # type: ignore
        from prometheus_client import Gauge as _G  # type: ignore
        global _M_LATENCY, _G_CANDIDATES, _G_ANN_PRUNE_RATIO, _G_ANN_BUILD_MS, _G_EXACT_MS, _G_AGG_MS
        _M_LATENCY = cast(HistogramLike, _H(
            "g6_pf_retrieval_latency_ms",
            "Retrieval forecaster total latency (ms)",
            buckets=_DEF_BUCKETS,
        ))
        _G_CANDIDATES = cast(GaugeLike, _G(
            "g6_pf_retrieval_candidates_total",
            "Number of candidate days retained",
        ))
        _G_ANN_PRUNE_RATIO = cast(GaugeLike, _G(
            "pf_ann_prune_ratio",
            "ANN shortlisted / total windows",
        ))
        _G_ANN_BUILD_MS = cast(GaugeLike, _G(
            "pf_ann_build_ms",
            "ANN build time in ms (0 on cache hit)",
        ))
        _G_EXACT_MS = cast(GaugeLike, _G(
            "pf_exact_scoring_ms",
            "Exact scoring time in ms",
        ))
        _G_AGG_MS = cast(GaugeLike, _G(
            "pf_quantile_agg_ms",
            "Quantile aggregation time in ms",
        ))
        
        # Phase 9: ANN cache metrics
        global _G_ANN_CACHE_HIT_RATIO, _G_ANN_CACHE_SIZE, _G_ANN_CACHE_EVICTIONS
        global _G_ANN_DISK_CACHE_HITS, _G_ANN_DISK_CACHE_LOAD_MS
        _G_ANN_CACHE_HIT_RATIO = cast(GaugeLike, _G(
            "g6_ml_ann_cache_hit_ratio",
            "ANN window cache hit ratio (0-1)",
        ))
        _G_ANN_CACHE_SIZE = cast(GaugeLike, _G(
            "g6_ml_ann_cache_size",
            "ANN window cache current size",
        ))
        _G_ANN_CACHE_EVICTIONS = cast(GaugeLike, _G(
            "g6_ml_ann_cache_evictions",
            "ANN window cache evictions total",
        ))
        _G_ANN_DISK_CACHE_HITS = cast(GaugeLike, _G(
            "g6_ml_ann_disk_cache_hits",
            "ANN disk cache hits total",
        ))
        _G_ANN_DISK_CACHE_LOAD_MS = cast(HistogramLike, _H(
            "g6_ml_ann_disk_cache_load_ms",
            "ANN disk cache load time in milliseconds",
            buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000],
        ))
        
        # Phase 9: Stage-level latency histograms
        global _M_STAGE_LATENCY
        for stage in ["data_load", "retrieval", "ann_build", "ann_reuse", "aggregation", "conformal"]:
            _M_STAGE_LATENCY[stage] = cast(HistogramLike, _H(
                "g6_ml_stage_latency_seconds",
                "Stage-level latency in seconds",
                labelnames=["stage", "index", "horizon"],
            ))
        
        # Optional: meta gauges & histograms (window/horizon, alpha, candidate richness)
        if os.environ.get("PATH_FORECAST_META_METRICS", "").strip() != "":
            global _G_WINDOW_SAN, _G_HORIZ_SAN, _M_ALPHA_HIST, _M_CANDIDATE_RICHNESS
            _G_WINDOW_SAN = cast(GaugeLike, _G(
                "g6_pf_window_sanitized",
                "Effective sanitized window length",
            ))
            _G_HORIZ_SAN = cast(GaugeLike, _G(
                "g6_pf_horizon_sanitized",
                "Effective sanitized horizon length",
            ))
            _M_ALPHA_HIST = cast(HistogramLike, _H(
                "g6_pf_alpha_hist",
                "Composite alpha distribution (0..1)",
                buckets=[0.0, 0.3, 0.5, 0.7, 0.9, 1.0],
            ))
            _M_CANDIDATE_RICHNESS = cast(HistogramLike, _H(
                "g6_pf_candidate_richness",
                "Candidate richness ratio (candidates/threshold)",
                buckets=[0.25, 0.5, 1.0, 1.5, 2.0, 3.0],
            ))
        # Composite
        global _M_COMP_LATENCY, _G_COMP_PRIOR_CACHE_HIT, _G_COMP_ALPHA, _G_COMP_PRIOR_DAYS, _G_COMP_RET_DAYS
        _M_COMP_LATENCY = cast(HistogramLike, _H(
            "g6_pf_composite_latency_ms",
            "Composite forecaster total latency (ms)",
            buckets=_DEF_BUCKETS,
        ))
        _G_COMP_PRIOR_CACHE_HIT = cast(GaugeLike, _G(
            "g6_pf_composite_prior_cache_hit",
            "Composite prior cache hit (0/1)",
        ))
        _G_COMP_ALPHA = cast(GaugeLike, _G(
            "g6_pf_composite_alpha",
            "Composite blend alpha",
        ))
        _G_COMP_PRIOR_DAYS = cast(GaugeLike, _G(
            "g6_pf_composite_prior_days",
            "Days contributing to prior",
        ))
        _G_COMP_RET_DAYS = cast(GaugeLike, _G(
            "g6_pf_composite_retained_days",
            "Retained candidate days in prior",
        ))
        _REG = True  # sentinel to mark initialized
        return _REG
    except (ImportError, AttributeError) as exc:
        # Prometheus client not available or incompatible version
        _LOG.debug(f"Metrics registration unavailable: {exc}")
        return None


def push_retrieval_metrics(meta: dict[str, Any]) -> None:
    reg = _get_reg()
    if reg is None:
        return
    try:
        cand = int(meta.get("candidates_total") or 0)
        if _G_CANDIDATES is not None:
            _G_CANDIDATES.set(cand)
        # Optional sanitized window/horizon gauges
        if _G_WINDOW_SAN is not None:
            w = meta.get("window_sanitized")
            if isinstance(w, (int, float)):
                _G_WINDOW_SAN.set(float(w))
        if _G_HORIZ_SAN is not None:
            h = meta.get("horizon_sanitized")
            if isinstance(h, (int, float)):
                _G_HORIZ_SAN.set(float(h))
        total_ms = meta.get("total_ms")
        if isinstance(total_ms, (int, float)) and _M_LATENCY is not None:
            _M_LATENCY.observe(float(total_ms))
        pr = meta.get("ann_prune_ratio")
        if isinstance(pr, (int, float)) and _G_ANN_PRUNE_RATIO is not None:
            _G_ANN_PRUNE_RATIO.set(float(pr))
        ab = meta.get("ann_build_ms")
        if isinstance(ab, (int, float)) and _G_ANN_BUILD_MS is not None:
            _G_ANN_BUILD_MS.set(float(ab))
        ex = meta.get("exact_scoring_ms")
        if isinstance(ex, (int, float)) and _G_EXACT_MS is not None:
            _G_EXACT_MS.set(float(ex))
        ag = meta.get("quantile_agg_ms")
        if isinstance(ag, (int, float)) and _G_AGG_MS is not None:
            _G_AGG_MS.set(float(ag))
        # Candidate richness histogram (candidates / max(threshold,1))
        if _M_CANDIDATE_RICHNESS is not None:
            thr = meta.get("threshold_needed")
            if isinstance(thr, (int, float)) and float(thr) > 0:
                ratio = float(cand) / float(thr)
                _M_CANDIDATE_RICHNESS.observe(ratio)
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        # Silently skip metrics push on invalid data (non-critical path)
        return


def push_composite_metrics(meta: dict[str, Any]) -> None:
        reg = _get_reg()
        if reg is None:
            return
        try:
            total_ms = meta.get("total_ms")
            if isinstance(total_ms, (int, float)) and _M_COMP_LATENCY is not None:
                _M_COMP_LATENCY.observe(float(total_ms))
            hit = meta.get("prior_cache_hit")
            if isinstance(hit, (int, float)) and _G_COMP_PRIOR_CACHE_HIT is not None:
                _G_COMP_PRIOR_CACHE_HIT.set(float(hit))
            alpha = meta.get("alpha")
            if isinstance(alpha, (int, float)) and _G_COMP_ALPHA is not None:
                _G_COMP_ALPHA.set(float(alpha))
            # Alpha histogram
            if isinstance(alpha, (int, float)) and _M_ALPHA_HIST is not None:
                _M_ALPHA_HIST.observe(float(alpha))
            pd = meta.get("prior_days")
            if isinstance(pd, (int, float)) and _G_COMP_PRIOR_DAYS is not None:
                _G_COMP_PRIOR_DAYS.set(float(pd))
            rd = meta.get("retained_days")
            if isinstance(rd, (int, float)) and _G_COMP_RET_DAYS is not None:
                _G_COMP_RET_DAYS.set(float(rd))
            # Mirror sanitized gauges if present in meta
            if _G_WINDOW_SAN is not None:
                w = meta.get("window_sanitized") or meta.get("window_used")
                if isinstance(w, (int, float)):
                    _G_WINDOW_SAN.set(float(w))
            if _G_HORIZ_SAN is not None:
                h = meta.get("horizon_sanitized")
                if isinstance(h, (int, float)):
                    _G_HORIZ_SAN.set(float(h))
        except (KeyError, ValueError, TypeError, AttributeError):
            # Silently skip metrics push on invalid data (non-critical path)
            return


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def compute_ann_effectiveness(
    ann_speedup: Optional[float],
    ann_prune_ratio: Optional[float],
    ann_q50_mad: Optional[float],
    tolerance: Optional[float],
) -> Optional[float]:
    """
    Compute a composite ANN effectiveness score.

    Components:
    - speedup: baseline_latency_ms / latency_ms
    - prune_gain: 1 - ann_prune_ratio (clamped to [0,1])
    - quality: 1 - clamp(ann_q50_mad / tolerance, 0..1)

    Returns None if required inputs are missing or invalid.
    """
    try:
        if ann_speedup is None:
            return None
        if ann_prune_ratio is None:
            return None
        if tolerance is None or tolerance <= 0:
            return None
        pr = _clamp(float(ann_prune_ratio), 0.0, 1.0)
        prune_gain = 1.0 - pr
        if ann_q50_mad is not None:
            q = float(ann_q50_mad) / float(tolerance)
            quality = 1.0 - _clamp(q, 0.0, 1.0)
        else:
            quality = 1.0
        return float(ann_speedup) * prune_gain * quality
    except (ValueError, TypeError, ZeroDivisionError):
        # Invalid input values for score calculation
        return None

def push_ann_cache_metrics(stats: dict[str, Any]) -> None:
    """Push ANN cache metrics to Prometheus.
    
    Args:
        stats: Dictionary with cache statistics from ann_cache module
    """
    reg = _get_reg()
    if reg is None:
        return
    
    try:
        if _G_ANN_CACHE_HIT_RATIO is not None:
            hit_ratio = float(stats.get('hit_ratio', 0.0))
            _G_ANN_CACHE_HIT_RATIO.set(hit_ratio)
        
        if _G_ANN_CACHE_SIZE is not None:
            size = int(stats.get('size', 0))
            _G_ANN_CACHE_SIZE.set(float(size))
        
        if _G_ANN_CACHE_EVICTIONS is not None:
            evictions = int(stats.get('evictions', 0))
            _G_ANN_CACHE_EVICTIONS.set(float(evictions))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        _LOG.debug(f"Failed to push ANN cache metrics: {exc}")


def push_ann_disk_cache_metrics(stats: dict[str, Any]) -> None:
    """Push ANN disk cache metrics to Prometheus.
    
    Args:
        stats: Dictionary with disk cache statistics from ann_cache module
    """
    reg = _get_reg()
    if reg is None:
        return
    
    try:
        if _G_ANN_DISK_CACHE_HITS is not None:
            hits = int(stats.get('hits', 0))
            _G_ANN_DISK_CACHE_HITS.set(float(hits))
        
        # Load time is recorded as a histogram observation
        load_ms = stats.get('load_ms')
        if load_ms is not None and _G_ANN_DISK_CACHE_LOAD_MS is not None:
            _G_ANN_DISK_CACHE_LOAD_MS.observe(float(load_ms))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        _LOG.debug(f"Failed to push ANN disk cache metrics: {exc}")


def observe_stage_latency(stage: str, latency_seconds: float, index: str = "", horizon: int = 0) -> None:
    """Observe stage-level latency.
    
    Args:
        stage: Stage name (data_load, retrieval, ann_build, ann_reuse, aggregation, conformal)
        latency_seconds: Latency in seconds
        index: Index name for label
        horizon: Horizon for label
    """
    reg = _get_reg()
    if reg is None:
        return
    
    try:
        if stage in _M_STAGE_LATENCY:
            metric = _M_STAGE_LATENCY[stage]
            # Use labels if metric supports them
            if hasattr(metric, 'labels'):
                metric.labels(stage=stage, index=index, horizon=str(horizon)).observe(latency_seconds)
            else:
                metric.observe(latency_seconds)
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        _LOG.debug(f"Failed to observe stage latency for {stage}: {exc}")


__all__ = [
    "compute_ann_effectiveness",
    "push_retrieval_metrics",
    "push_composite_metrics",
    "push_ann_cache_metrics",
    "push_ann_disk_cache_metrics",
    "observe_stage_latency",
]
