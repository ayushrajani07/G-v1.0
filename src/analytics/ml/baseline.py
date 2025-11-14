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
