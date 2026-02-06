from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


def parse_int_ms(raw: object) -> int | None:
    """Best-effort parse of an epoch-ms-ish value.

    Accepts ints or strings; returns None for empty/invalid inputs.
    """

    if raw is None:
        return None
    s = f"{raw}".strip()
    if not s:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def infer_now_ms_from_rows(rows: list[dict[str, Any]]) -> int | None:
    """Infer a 'now' timestamp from live rows.

    Uses max of `ts` or `time` fields when present.
    """

    if not rows:
        return None
    max_ms: int | None = None
    for row in rows:
        try:
            raw = row.get("ts") or row.get("time")
        except (AttributeError, TypeError):
            raw = None
        ems = parse_int_ms(raw)
        if not ems:
            continue
        if max_ms is None or ems > max_ms:
            max_ms = ems
    return max_ms


def build_realized_map_and_times(
    rows: list[dict[str, Any]],
    *,
    bucket_ms: int | None,
    tp_getter: Callable[[dict[str, Any]], object],
    non_negative: bool = False,
) -> tuple[dict[int, float], list[int]]:
    """Build a realized TP map keyed by (optionally bucketed) time.

    Returns (realized_map, sorted_unique_times).
    """

    realized: dict[int, float] = {}
    times: list[int] = []
    for row in rows:
        try:
            raw_ts = row.get("ts") or row.get("time")
        except (AttributeError, TypeError):
            raw_ts = None
        ems = parse_int_ms(raw_ts)
        if not ems:
            continue
        try:
            tp_raw = tp_getter(row)
        except BaseException as e:
            import asyncio
            if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                raise
            continue
        if not isinstance(tp_raw, (int, float)):
            continue
        tp = float(tp_raw)
        if non_negative and tp < 0:
            tp = 0.0
        if bucket_ms:
            t = (int(ems) // int(bucket_ms)) * int(bucket_ms)
        else:
            t = int(ems)
        realized[t] = tp
        times.append(t)
    ts_sorted = sorted(set(times))
    return realized, ts_sorted


def now_and_cutoff(ts_sorted: Sequence[int], window_minutes: int) -> tuple[int | None, int | None]:
    """Compute (now_ms, cutoff_gen_ms) from a sorted time series."""

    if not ts_sorted:
        return None, None
    now_ms = int(ts_sorted[-1])
    cutoff_gen = now_ms - int(window_minutes) * 60_000
    return now_ms, cutoff_gen


def nearest_time_key(ts_sorted: Sequence[int], target_ms: int, tol_ms: int) -> int | None:
    """Return nearest key in ts_sorted within tol_ms of target_ms.

    `ts_sorted` must be sorted ascending.
    """

    if not ts_sorted:
        return None
    try:
        import bisect

        j = bisect.bisect_left(ts_sorted, int(target_ms))
    except (TypeError, ValueError):
        return None

    best_r: int | None = None
    best_d: int | None = None
    try:
        if j < len(ts_sorted):
            rts = int(ts_sorted[j])
            d = abs(rts - int(target_ms))
            best_r, best_d = rts, d
        if j > 0:
            rts2 = int(ts_sorted[j - 1])
            d2 = abs(rts2 - int(target_ms))
            if best_d is None or d2 < best_d:
                best_r, best_d = rts2, d2
    except (IndexError, TypeError, ValueError):
        return None

    if best_r is None or best_d is None:
        return None
    if int(best_d) > int(tol_ms):
        return None
    return best_r


def clamp_ms_to_rows(nm: int, rows: list[dict[str, Any]]) -> int:
    """Clamp nm to the [min_ts, max_ts] range of the given rows when possible."""

    if not rows:
        return nm
    min_ms: int | None = None
    max_ms: int | None = None
    for row in rows:
        try:
            raw = row.get("ts") or row.get("time")
        except (AttributeError, TypeError):
            raw = None
        ems = parse_int_ms(raw)
        if not ems:
            continue
        if min_ms is None or ems < min_ms:
            min_ms = ems
        if max_ms is None or ems > max_ms:
            max_ms = ems
    if min_ms is not None and nm < min_ms:
        nm = min_ms
    if max_ms is not None and nm > max_ms:
        nm = max_ms
    return nm


def extract_now_override_raw(now_override_ms: str | None, query_params: Mapping[str, str]) -> str | None:
    """Match legacy query-param fallbacks for now override selection."""

    return (
        now_override_ms
        or query_params.get("now_override_ms")
        or query_params.get("nowMs")
        or query_params.get("now_ms")
        or query_params.get("now")
    )


__all__ = [
    "parse_int_ms",
    "infer_now_ms_from_rows",
    "build_realized_map_and_times",
    "now_and_cutoff",
    "nearest_time_key",
    "clamp_ms_to_rows",
    "extract_now_override_raw",
]
