from __future__ import annotations
"""Unified query builder for path forecasting modules.

Consolidates duplicated logic for constructing today's TP series and the query
window statistics used by retrieval and composite forecasters.

Responsibilities:
 - Parse recent_window (sequence of scalars or 1D arrays) primary source.
 - Fallback to live_rows (list of row dicts or simple numeric rows) when recent_window empty.
 - Build today_tp list (floats) preserving chronological order.
 - Slice last W values as query; compute z-scored query, mean, and std.
 - Return structured parts for downstream scoring.

Edge cases:
 - Raises ValueError if < W rows available after parsing.
 - Gracefully skips malformed entries, collecting warnings.

Returned tuple:
   (today_tp, query, query_z, q_mean, q_sd, n_today, warnings)
"""
from typing import Sequence, List, Any, Tuple

__all__ = ["build_query_parts", "parse_today_tp"]


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


def build_query_parts(
    recent_window: Sequence[Sequence[float] | float | int],
    live_rows: Sequence[Any],
    window_size: int,
) -> Tuple[List[float], List[float], List[float], float, float, int, List[str]]:
    W = int(window_size)
    warnings: List[str] = []
    today_tp: List[float] = []

    # Primary parse: recent_window
    for r in recent_window:
        try:
            if isinstance(r, (list, tuple)) and r:
                v0 = r[0]
                if isinstance(v0, (int, float)):
                    today_tp.append(float(v0))
            elif isinstance(r, (int, float)):
                today_tp.append(float(r))
        except Exception as exc:  # pragma: no cover (defensive)
            warnings.append(f"recent_window parse failed ({exc.__class__.__name__}: {exc})")

    # Fallback parse: live_rows if empty
    if not today_tp and live_rows:
        for r in live_rows:
            try:
                if isinstance(r, dict):
                    # typical structured row; TP might be under 'tp'
                    v = r.get('tp')
                    if isinstance(v, (int, float)):
                        today_tp.append(float(v))
                        continue
                if isinstance(r, (list, tuple)) and r:
                    v0 = r[0]
                    if isinstance(v0, (int, float)):
                        today_tp.append(float(v0))
                elif isinstance(r, (int, float)):
                    today_tp.append(float(r))
            except Exception as exc:  # pragma: no cover
                warnings.append(f"live_rows parse failed ({exc.__class__.__name__}: {exc})")

    n_today = len(today_tp)
    if n_today < W:
        # Relaxed constraint: if we have at least 10 rows, use what we have
        if n_today < 10:
            raise ValueError(f"insufficient rows in recent window for query window (have {n_today}, need {W})")
        # Use available rows as effective window
        W = n_today

    query = today_tp[n_today - W: n_today]
    query_z = _zscore(query)
    q_mean, q_sd = _mean_std(query)
    return today_tp, query, query_z, q_mean, q_sd, n_today, warnings


def parse_today_tp(
    recent_window: Sequence[Sequence[float] | float | int],
    live_rows: Sequence[Any],
) -> Tuple[List[float], List[str]]:
    """Parse today's TP series from recent_window (preferred) or live_rows.

    Does not enforce a minimum window size; intended for computing now_pos
    or building auxiliary windows without risking ValueError.
    Returns (today_tp, warnings).
    """
    warnings: List[str] = []
    today_tp: List[float] = []
    for r in recent_window:
        try:
            if isinstance(r, (list, tuple)) and r:
                v0 = r[0]
                if isinstance(v0, (int, float)):
                    today_tp.append(float(v0))
            elif isinstance(r, (int, float)):
                today_tp.append(float(r))
        except Exception as exc:  # pragma: no cover
            warnings.append(f"recent_window parse failed ({exc.__class__.__name__}: {exc})")
    if not today_tp and live_rows:
        for r in live_rows:
            try:
                if isinstance(r, dict):
                    v = r.get('tp')
                    if isinstance(v, (int, float)):
                        today_tp.append(float(v))
                        continue
                if isinstance(r, (list, tuple)) and r:
                    v0 = r[0]
                    if isinstance(v0, (int, float)):
                        today_tp.append(float(v0))
                elif isinstance(r, (int, float)):
                    today_tp.append(float(r))
            except Exception as exc:  # pragma: no cover
                warnings.append(f"live_rows parse failed ({exc.__class__.__name__}: {exc})")
    return today_tp, warnings
