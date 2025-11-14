from __future__ import annotations

"""Common helpers for path-forecast modules.

Centralizes repeated utilities:
 - extract_tp(row): robust TP extraction from multiple schemas
 - row_time_ms(row): timestamp in ms from ts/time_ms/ISO time
 - effective_window_since_open(now_ms, configured): 0 => since market open
 - build_recent_window(rows, now_ms, window_min): last W minutes values as [[tp], ...]
 - build_bucketed_realized(rows, bucket_ms): (sorted_ts, {ts_bucket: tp})

Keep this dependency-light (no pandas/numpy) and pure where possible.
"""

from typing import Iterable, List, Tuple, Dict, Optional, Any
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def extract_tp(row: dict) -> Optional[float]:
    """Best-effort extraction of realized TP from a CSV row.

    Priority:
      1. tp
      2. avg_tp
      3. extended total premium synonyms (tp_total,total_premium,straddle_premium,atm_straddle)
      4. (ce + pe) across broad synonym sets

    - Accepts numeric or numeric-like strings
    - Clamps negatives to 0.0 (TP cannot be negative)
    """
    def _to_float(x) -> Optional[float]:
        try:
            if x is None or x == "":
                return None
            return float(x)
        except Exception:
            return None

    # Direct fields
    tp_direct = _to_float(row.get("tp"))
    if tp_direct is not None:
        # Clamp negative direct tp to 0.0
        if tp_direct < 0:
            return 0.0
        return tp_direct
    avg_tp = _to_float(row.get("avg_tp"))
    if avg_tp is not None:
        return max(0.0, avg_tp)

    # Total premium style synonyms (clamp negative totals)
    for key in ("tp_total", "total_premium", "straddle_premium", "atm_straddle"):
        v = _to_float(row.get(key))
        if v is not None:
            return max(0.0, v)

    # Broader ce/pe synonym sets
    ce_keys = ("ce","ce_ltp","atm_ce","call_ltp","call","atm_call","ce_price","atm_ce_ltp")
    pe_keys = ("pe","pe_ltp","atm_pe","put_ltp","put","atm_put","pe_price","atm_pe_ltp")
    ce_val = None
    pe_val = None
    for ck in ce_keys:
        ce_val = _to_float(row.get(ck))
        if ce_val is not None:
            break
    for pk in pe_keys:
        pe_val = _to_float(row.get(pk))
        if pe_val is not None:
            break
    if ce_val is not None and pe_val is not None:
        total = (ce_val if isinstance(ce_val, (int, float)) else 0.0) + (pe_val if isinstance(pe_val, (int, float)) else 0.0)
        return max(0.0, float(total))
    return None


def row_time_ms(row: dict) -> Optional[int]:
    """Extract timestamp (ms) from common keys: ts, time_ms, time (ISO)."""
    for key in ("ts", "time_ms"):
        try:
            v = row.get(key)
            if v is None or v == "":
                continue
            return int(float(v))
        except Exception:
            continue
    tstr = row.get("time")
    if isinstance(tstr, str) and tstr:
        try:
            dt = datetime.fromisoformat(tstr)
            return int(dt.timestamp() * 1000)
        except Exception:
            return None
    return None


def effective_window_since_open(now_ms: Optional[int], configured_window: int) -> int:
    """Return effective window; 0 => since 09:15 IST up to now_ms, bounded [10,720]."""
    try:
        w = int(configured_window)
    except Exception:
        w = 60
    if w != 0 or not now_ms:
        return max(10, min(720, w))
    try:
        dt_now = datetime.fromtimestamp(int(now_ms) / 1000.0, tz=IST)
        open_dt = datetime(dt_now.year, dt_now.month, dt_now.day, 9, 15, tzinfo=IST)
        if dt_now <= open_dt:
            return 10
        mins = int((dt_now - open_dt).total_seconds() // 60)
        return max(10, min(720, mins))
    except Exception:
        return 60


def build_recent_window(rows: Iterable[dict], now_ms: int, window_min: int) -> List[List[float]]:
    """Collect last window_min minutes up to now_ms as [[tp], ...], 1 per minute approx.

    Simpler heuristic: take last W values by order for stability across minor jitter.
    """
    vals: List[float] = []
    for r in rows:
        t = row_time_ms(r)
        if not isinstance(t, int) or t <= 0 or t > now_ms:
            continue
        v = extract_tp(r)
        if isinstance(v, (int, float)):
            vals.append(float(v))
    W = max(10, min(720, int(window_min)))
    seq = vals[-W:]
    return [[float(v)] for v in seq]


def build_bucketed_realized(rows: Iterable[dict], bucket_ms: int) -> Tuple[List[int], Dict[int, float]]:
    """Return (sorted_bucket_ts, {bucket_ts: tp}) by snapping to bucket grid.

    Keeps last value per bucket.
    """
    bmap: Dict[int, float] = {}
    for r in rows:
        t = row_time_ms(r)
        if not isinstance(t, int) or t <= 0:
            continue
        v = extract_tp(r)
        if not isinstance(v, (int, float)):
            continue
        b = (int(t) // int(bucket_ms)) * int(bucket_ms)
        bmap[b] = float(v)
    ts_sorted = sorted(bmap.keys())
    return ts_sorted, bmap


__all__ = [
    "extract_tp",
    "row_time_ms",
    "effective_window_since_open",
    "build_recent_window",
    "build_bucketed_realized",
    "safe_int",
    "safe_float",
    "clamp",
    "env_flag",
]


def clamp(x: float, lo: float, hi: float) -> float:
    try:
        v = float(x)
        return max(float(lo), min(float(hi), v))
    except Exception:
        return float(lo)


def safe_int(x: Any, default: int = 0, *, min_: Optional[int] = None, max_: Optional[int] = None) -> int:
    """Parse int safely with optional bounds; returns default on failure."""
    try:
        v = int(float(x))
    except Exception:
        return int(default)
    if min_ is not None and v < int(min_):
        v = int(min_)
    if max_ is not None and v > int(max_):
        v = int(max_)
    return v


def safe_float(x: Any, default: Optional[float] = 0.0, *, min_: Optional[float] = None, max_: Optional[float] = None) -> Optional[float]:
    """Parse float safely with optional bounds; returns default on failure."""
    try:
        v = float(x)
    except Exception:
        return default
    if min_ is not None and v < float(min_):
        v = float(min_)
    if max_ is not None and v > float(max_):
        v = float(max_)
    return v


def env_flag(name: str) -> bool:
    """Truthy env flag: returns True if env var is set and not in ("", "0", "false", "False")."""
    import os
    v = os.environ.get(name)
    if v is None:
        return False
    s = str(v).strip().lower()
    return s not in ("", "0", "false", "no", "off")
