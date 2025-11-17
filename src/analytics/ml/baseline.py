from __future__ import annotations

"""
Simple structural baseline for ATM Total Premium (TP).

Baseline formula (scaled Bachelier-like proxy):
  baseline_tp = k * underlying * iv_proxy * sqrt(T)
where
  - underlying: index spot price
  - iv_proxy: average of CE/PE IVs (as decimal, e.g., 0.20 for 20%) or provided directly
  - T: time to expiry in trading days (minutes_to_expiry / (60*24))
  - k: scalar coefficient to tune overall scaling (default 1.0)

The intent is to capture structural dependence of TP on underlying, implied vol, and time-to-expiry,
leaving residuals to a ML regressor.
"""

import math
from typing import Optional

try:
    import pandas as pd
    import numpy as np
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


def _safe_float(x: Optional[float], default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def baseline_tp(underlying: float,
                iv_proxy: Optional[float] = None,
                ce_iv: Optional[float] = None,
                pe_iv: Optional[float] = None,
                minutes_to_expiry: Optional[float] = None,
                k: float = 1.0,
                min_iv: float = 1e-4,
                min_T_minutes: float = 1.0) -> float:
    """Compute structural baseline TP.

    Inputs:
      - underlying: index spot price (>0)
      - iv_proxy: decimal IV (e.g., 0.2), if None, avg(ce_iv, pe_iv) used
      - ce_iv, pe_iv: optional legs IV; used only if iv_proxy is None
      - minutes_to_expiry: minutes remaining to expiry (>0). If None, min_T_minutes used
      - k: scaling coefficient
      - min_iv: lower bound for IV (avoid zero)
      - min_T_minutes: lower bound for minutes_to_expiry

    Returns:
      - baseline TP (float >= 0)
    """
    u = max(float(_safe_float(underlying, 0.0) or 0.0), 0.0)
    # Resolve IV
    if iv_proxy is None:
        ce = _safe_float(ce_iv, None) if ce_iv is not None else None
        pe = _safe_float(pe_iv, None) if pe_iv is not None else None
        if ce is not None and pe is not None:
            iv = 0.5 * (ce + pe)
        elif ce is not None:
            iv = ce
        elif pe is not None:
            iv = pe
        else:
            iv = 0.0
    else:
        iv = float(_safe_float(iv_proxy, 0.0) or 0.0)
    iv = max(iv, min_iv)

    # Resolve T in trading days
    m2e = max(float(_safe_float(minutes_to_expiry, min_T_minutes) or min_T_minutes), min_T_minutes)
    T = m2e / (60.0 * 24.0)
    # Baseline
    base = float(max(0.0, k) * u * iv * math.sqrt(max(T, 0.0)))
    return base


def baseline_tp_batch(
    df,
    underlying_col: str = "underlying",
    iv_col: Optional[str] = None,
    ce_iv_col: Optional[str] = None,
    pe_iv_col: Optional[str] = None,
    minutes_to_expiry_col: str = "minutes_to_expiry",
    output_col: str = "tp_baseline",
    k: float = 1.0,
    min_iv: float = 1e-4,
    min_T_minutes: float = 1.0,
):
    """Compute baseline TP for a batch of data (DataFrame).
    
    Args:
        df: Input DataFrame or pandas-compatible object
        underlying_col: Column name for underlying price
        iv_col: Column name for IV proxy (if available)
        ce_iv_col: Column name for CE IV (used if iv_col not provided)
        pe_iv_col: Column name for PE IV (used if iv_col not provided)
        minutes_to_expiry_col: Column name for time to expiry
        output_col: Column name for output baseline TP
        k: Scaling coefficient
        min_iv: Minimum IV value
        min_T_minutes: Minimum time to expiry in minutes
        
    Returns:
        DataFrame with added baseline TP column
        
    Raises:
        RuntimeError: If pandas is not available
    """
    if not HAS_PANDAS:
        raise RuntimeError("pandas is required for batch processing")
    
    # Make a copy to avoid modifying input
    result = df.copy()
    
    # Extract underlying prices
    underlying = result[underlying_col].values
    
    # Resolve IV
    if iv_col is not None and iv_col in result.columns:
        iv = result[iv_col].values
    elif ce_iv_col in result.columns and pe_iv_col in result.columns:
        ce = result[ce_iv_col].values
        pe = result[pe_iv_col].values
        iv = 0.5 * (ce + pe)
    elif ce_iv_col in result.columns:
        iv = result[ce_iv_col].values
    elif pe_iv_col in result.columns:
        iv = result[pe_iv_col].values
    else:
        iv = np.full(len(result), 0.0)
    
    # Apply bounds
    iv = np.maximum(iv, min_iv)
    
    # Extract time to expiry
    minutes_to_expiry = result[minutes_to_expiry_col].values
    minutes_to_expiry = np.maximum(minutes_to_expiry, min_T_minutes)
    T = minutes_to_expiry / (60.0 * 24.0)
    
    # Compute baseline: k * underlying * iv * sqrt(T)
    baseline = k * underlying * iv * np.sqrt(T)
    baseline = np.maximum(baseline, 0.0)
    
    # Add to result
    result[output_col] = baseline
    
    return result


def compute_residuals(
    df,
    tp_actual_col: str = "tp_actual",
    tp_baseline_col: str = "tp_baseline",
    residual_col: str = "tp_residual",
):
    """Compute residuals: actual - baseline.
    
    Args:
        df: Input DataFrame
        tp_actual_col: Column name for actual TP
        tp_baseline_col: Column name for baseline TP
        residual_col: Column name for output residual
        
    Returns:
        DataFrame with added residual column
    """
    if not HAS_PANDAS:
        raise RuntimeError("pandas is required for batch processing")
    
    result = df.copy()
    result[residual_col] = result[tp_actual_col] - result[tp_baseline_col]
    return result


# Phase 7.2: Alternative baseline formulas for validation


def baseline_tp_sublinear(
    underlying: float,
    iv_proxy: Optional[float] = None,
    ce_iv: Optional[float] = None,
    pe_iv: Optional[float] = None,
    minutes_to_expiry: Optional[float] = None,
    k: float = 1.0,
    min_iv: float = 1e-4,
    min_T_minutes: float = 1.0
) -> float:
    """Alternative baseline with sub-linear index price scaling.
    
    Formula: baseline_tp = k * sqrt(underlying) * iv * sqrt(T)
    
    This captures the idea that premium may not scale linearly with spot price.
    Useful for testing if linear scaling assumption is too strong.
    
    Args:
        Same as baseline_tp()
        
    Returns:
        Baseline TP with sub-linear price scaling
    """
    u = max(float(_safe_float(underlying, 0.0) or 0.0), 0.0)
    
    # Resolve IV (same logic as baseline_tp)
    if iv_proxy is None:
        ce = _safe_float(ce_iv, None) if ce_iv is not None else None
        pe = _safe_float(pe_iv, None) if pe_iv is not None else None
        if ce is not None and pe is not None:
            iv = 0.5 * (ce + pe)
        elif ce is not None:
            iv = ce
        elif pe is not None:
            iv = pe
        else:
            iv = 0.0
    else:
        iv = float(_safe_float(iv_proxy, 0.0) or 0.0)
    iv = max(iv, min_iv)
    
    # Resolve T
    m2e = max(float(_safe_float(minutes_to_expiry, min_T_minutes) or min_T_minutes), min_T_minutes)
    T = m2e / (60.0 * 24.0)
    
    # Sub-linear scaling: sqrt(underlying)
    base = float(max(0.0, k) * math.sqrt(u) * iv * math.sqrt(max(T, 0.0)))
    return base


def baseline_tp_log(
    underlying: float,
    iv_proxy: Optional[float] = None,
    ce_iv: Optional[float] = None,
    pe_iv: Optional[float] = None,
    minutes_to_expiry: Optional[float] = None,
    k: float = 1.0,
    min_iv: float = 1e-4,
    min_T_minutes: float = 1.0
) -> float:
    """Alternative baseline with log index price scaling.
    
    Formula: baseline_tp = k * log(underlying) * iv * T
    
    This captures even weaker price scaling and uses T instead of sqrt(T).
    Useful for testing if the relationship is more logarithmic.
    
    Args:
        Same as baseline_tp()
        
    Returns:
        Baseline TP with log price scaling
    """
    u = max(float(_safe_float(underlying, 0.0) or 0.0), 1.0)  # Avoid log(0)
    
    # Resolve IV
    if iv_proxy is None:
        ce = _safe_float(ce_iv, None) if ce_iv is not None else None
        pe = _safe_float(pe_iv, None) if pe_iv is not None else None
        if ce is not None and pe is not None:
            iv = 0.5 * (ce + pe)
        elif ce is not None:
            iv = ce
        elif pe is not None:
            iv = pe
        else:
            iv = 0.0
    else:
        iv = float(_safe_float(iv_proxy, 0.0) or 0.0)
    iv = max(iv, min_iv)
    
    # Resolve T
    m2e = max(float(_safe_float(minutes_to_expiry, min_T_minutes) or min_T_minutes), min_T_minutes)
    T = m2e / (60.0 * 24.0)
    
    # Log scaling
    base = float(max(0.0, k) * math.log(u) * iv * T)
    return base


def compare_baseline_formulas(
    df,
    tp_actual_col: str = "tp_actual",
    underlying_col: str = "underlying",
    iv_col: Optional[str] = None,
    ce_iv_col: Optional[str] = None,
    pe_iv_col: Optional[str] = None,
    minutes_to_expiry_col: str = "minutes_to_expiry",
    k: float = 1.0,
):
    """Compare different baseline formulas on the same dataset.
    
    Computes:
    1. Linear baseline (default): k * underlying * iv * sqrt(T)
    2. Sub-linear baseline: k * sqrt(underlying) * iv * sqrt(T)
    3. Log baseline: k * log(underlying) * iv * T
    
    Returns comparison metrics (MAE, RMSE, correlation) for each.
    
    Args:
        df: Input DataFrame with historical data
        tp_actual_col: Column name for actual TP values
        underlying_col: Column name for underlying price
        iv_col: Column name for IV (optional)
        ce_iv_col, pe_iv_col: CE/PE IV columns (used if iv_col not provided)
        minutes_to_expiry_col: Column name for time to expiry
        k: Scaling coefficient
        
    Returns:
        Dictionary with comparison metrics for each formula
    """
    if not HAS_PANDAS:
        raise RuntimeError("pandas is required")
    
    # Compute all three baselines
    df_linear = baseline_tp_batch(
        df, underlying_col, iv_col, ce_iv_col, pe_iv_col,
        minutes_to_expiry_col, "tp_baseline_linear", k
    )
    
    # Sub-linear formula (batch version)
    underlying = df[underlying_col].values
    if iv_col and iv_col in df.columns:
        iv = df[iv_col].values
    elif ce_iv_col in df.columns and pe_iv_col in df.columns:
        iv = 0.5 * (df[ce_iv_col].values + df[pe_iv_col].values)
    else:
        iv = np.full(len(df), 0.15)
    
    minutes_to_expiry = df[minutes_to_expiry_col].values
    T = np.maximum(minutes_to_expiry, 1.0) / (60.0 * 24.0)
    
    df_linear["tp_baseline_sublinear"] = k * np.sqrt(underlying) * iv * np.sqrt(T)
    df_linear["tp_baseline_log"] = k * np.log(np.maximum(underlying, 1.0)) * iv * T
    
    # Compute metrics
    tp_actual = df_linear[tp_actual_col].values
    
    results = {}
    for formula_name in ["linear", "sublinear", "log"]:
        baseline_col = f"tp_baseline_{formula_name}"
        baseline = df_linear[baseline_col].values
        residual = tp_actual - baseline
        
        results[formula_name] = {
            "mae": float(np.mean(np.abs(residual))),
            "rmse": float(np.sqrt(np.mean(residual ** 2))),
            "correlation": float(np.corrcoef(tp_actual, baseline)[0, 1]),
            "mean_residual": float(np.mean(residual)),
            "std_residual": float(np.std(residual)),
        }
    
    return results
