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
