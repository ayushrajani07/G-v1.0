from __future__ import annotations

"""Centralized parameter bounds and sanitization helpers.

Use to keep magic numbers in one place and ensure consistent clamping.
"""
from typing import Any, Optional

from .common import safe_int, safe_float, clamp

# Default parameters for ensemble/composite forecasting
DEFAULT_ALPHA_MIN = 0.3
DEFAULT_ALPHA_MAX = 0.9
DEFAULT_RECENT_GAMMA = 0.9
DEFAULT_PRIOR_CACHE_MAX = 256
PRIOR_CACHE_MIN = 16
PRIOR_CACHE_MAX = 4096

# Default parameters for conformal prediction
CONFORMAL_DEFAULT_COVERAGE = 0.8
CONFORMAL_DEFAULT_WINDOW = 600

# Default parameters for retrieval
RETRIEVAL_DEFAULT_K = 15
RETRIEVAL_DEFAULT_WINDOW = 60
RETRIEVAL_MIN_DAYS = 3

# Bounds catalog (document-only; helpers implement usage)
SANITIZED_BOUNDS = {
    "window": (1, 720),
    "horizon": (1, 720),
    "bucket_ms": (1_000, 300_000),
    "k": (1, 1000),
    "min_days": (1, 1000),
    "max_days_scan": (0, 10_000),
    "min_hist_rows": (0, 200_000),
    "ann_max_candidates": (0, 10_000),
    "recent_gamma": (0.01, 0.999),
    "regime_tolerance": (0.0, 10.0),
    "regime_penalty": (1.0, 10.0),
}


def sanitize_window(v: Any, default: int = 60) -> int:
    lo, hi = SANITIZED_BOUNDS["window"]
    return safe_int(v, default, min_=lo, max_=hi)


def sanitize_horizon(v: Any, default: int = 60) -> int:
    lo, hi = SANITIZED_BOUNDS["horizon"]
    return safe_int(v, default, min_=lo, max_=hi)


def sanitize_bucket_ms(v: Any, default: int = 60_000) -> int:
    lo, hi = SANITIZED_BOUNDS["bucket_ms"]
    return safe_int(v, default, min_=lo, max_=hi)


def sanitize_k(v: Any, default: int = 15) -> int:
    lo, hi = SANITIZED_BOUNDS["k"]
    return safe_int(v, default, min_=lo, max_=hi)


def sanitize_min_days(v: Any, default: int = 3) -> int:
    lo, hi = SANITIZED_BOUNDS["min_days"]
    return safe_int(v, default, min_=lo, max_=hi)


def sanitize_max_days_scan(v: Any, default: int = 0) -> int:
    lo, hi = SANITIZED_BOUNDS["max_days_scan"]
    return safe_int(v, default, min_=lo, max_=hi)


def sanitize_min_hist_rows(v: Any, default: int = 0) -> int:
    lo, hi = SANITIZED_BOUNDS["min_hist_rows"]
    return safe_int(v, default, min_=lo, max_=hi)


def sanitize_ann_max_candidates(v: Any, default: int = 0) -> int:
    lo, hi = SANITIZED_BOUNDS["ann_max_candidates"]
    return safe_int(v, default, min_=lo, max_=hi)


def sanitize_recent_gamma(v: Any, default: float = 0.9) -> float:
    lo, hi = SANITIZED_BOUNDS["recent_gamma"]
    val = safe_float(v, default, min_=lo, max_=hi)
    return float(val if val is not None else default)


def sanitize_regime_tolerance(v: Any, default: Optional[float] = None) -> Optional[float]:
    lo, hi = SANITIZED_BOUNDS["regime_tolerance"]
    return safe_float(v, default, min_=lo, max_=hi)


def sanitize_regime_penalty(v: Any, default: float = 1.25) -> float:
    lo, hi = SANITIZED_BOUNDS["regime_penalty"]
    val = safe_float(v, default, min_=lo, max_=hi)
    return float(val if val is not None else default)


def clamp_alpha(v: float) -> float:
    return clamp(v, DEFAULT_ALPHA_MIN, DEFAULT_ALPHA_MAX)

def sanitize_ann_dim(v: Any, window_default: int) -> int:
    """Sanitize ANN dimension.

    - Defaults to the sanitized window length provided by caller.
    - Clamps to [1, window_default] to ensure the vector length never exceeds the window size.
    """
    # Note: we intentionally don't add a static bound in SANITIZED_BOUNDS because the
    # upper limit depends on the runtime window size.
    return safe_int(v, window_default, min_=1, max_=window_default)

__all__ = [
    "SANITIZED_BOUNDS",
    "DEFAULT_ALPHA_MIN",
    "DEFAULT_ALPHA_MAX",
    "DEFAULT_RECENT_GAMMA",
    "DEFAULT_PRIOR_CACHE_MAX",
    "PRIOR_CACHE_MIN",
    "PRIOR_CACHE_MAX",
    "CONFORMAL_DEFAULT_COVERAGE",
    "CONFORMAL_DEFAULT_WINDOW",
    "RETRIEVAL_DEFAULT_K",
    "RETRIEVAL_DEFAULT_WINDOW",
    "RETRIEVAL_MIN_DAYS",
    "sanitize_window",
    "sanitize_horizon",
    "sanitize_bucket_ms",
    "sanitize_k",
    "sanitize_min_days",
    "sanitize_max_days_scan",
    "sanitize_min_hist_rows",
    "sanitize_ann_max_candidates",
    "sanitize_recent_gamma",
    "sanitize_regime_tolerance",
    "sanitize_regime_penalty",
    "sanitize_ann_dim",
    "clamp_alpha",
]
