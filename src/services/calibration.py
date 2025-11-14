"""Calibration helpers extracted from path_forecast route.

Provides:
    load_calibration(index) -> dict
    apply_band_scale(qmap, scale) -> scaled qmap
    clamp_non_negative(qmap) -> clamped qmap

Stateless, pure transformations (except file IO in load_calibration).
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Dict
import json
import datetime as _dt

_DEFAULT = {"band_scale": 1.0, "updated_at": None, "target": None, "actual": None, "samples": None}

def _project_root() -> Path:  # lightweight duplication to avoid circular import
    # NOTE: Adjust if repository root heuristic changes.
    return Path(__file__).resolve().parents[2]

def load_calibration(index: str) -> dict:
    idx = (index or "NIFTY").strip().upper()
    path = _project_root() / "data" / "ml" / "path_forecasts" / "_calibration" / f"{idx}.json"
    out = dict(_DEFAULT)
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k,v in data.items():
                    out[k] = v
    except Exception:
        pass
    # basic validation
    try:
        bs = float(out.get("band_scale", 1.0))
        if not (0.05 <= bs <= 10.0):
            out["band_scale"] = 1.0
    except Exception:
        out["band_scale"] = 1.0
    return out

def apply_band_scale(qmap: Dict[float, Sequence[float]] | dict, scale: float) -> Dict[float, list[float]]:
    s = float(scale) if isinstance(scale, (int, float)) else 1.0
    if s <= 0:
        s = 1.0
    out10: list[float] = []
    out50: list[float] = []
    out90: list[float] = []
    q10 = list(qmap.get(0.1) or [])  # type: ignore[index]
    q50 = list(qmap.get(0.5) or [])  # type: ignore[index]
    q90 = list(qmap.get(0.9) or [])  # type: ignore[index]
    H = max(len(q10), len(q50), len(q90))
    for i in range(H):
        m = q50[i] if i < len(q50) else None
        lo = q10[i] if i < len(q10) else None
        hi = q90[i] if i < len(q90) else None
        if not isinstance(m, (int, float)):
            # preserve positional length with placeholder 0.0 when median missing
            out50.append(0.0)
            out10.append(0.0)
            out90.append(0.0)
            continue
        m_f = float(m)
        out50.append(m_f)
        if isinstance(lo, (int, float)):
            lo_scaled = m_f - (m_f - float(lo)) * s
            if lo_scaled < 0:
                lo_scaled = 0.0
            out10.append(float(lo_scaled))
        else:
            out10.append(m_f)  # collapse to median when missing
        if isinstance(hi, (int, float)):
            out90.append(float(m_f + (float(hi) - m_f) * s))
        else:
            out90.append(m_f)
    return {0.1: out10, 0.5: out50, 0.9: out90}

def clamp_non_negative(qmap: Dict[float, Sequence[float]] | dict) -> Dict[float, list[float]]:
    out: Dict[float, list[float]] = {}
    for q in (0.1, 0.5, 0.9):
        seq = list(qmap.get(q) or [])  # type: ignore[index]
        clamped: list[float] = []
        for v in seq:
            if isinstance(v, (int, float)):
                clamped.append(v if v >= 0 else 0.0)
            else:
                # replace None / invalid with 0.0 to satisfy typing and downstream math
                clamped.append(0.0)
        out[q] = clamped
    return out

__all__ = ["load_calibration", "apply_band_scale", "clamp_non_negative"]