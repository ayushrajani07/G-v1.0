from __future__ import annotations

import time
from typing import Any

# Lightweight in-process observability store
OBS: dict[str, Any] = {
    "live_csv": {"count": 0, "errors": 0, "too_many": 0, "dur_ms_sum": 0.0, "dur_ms_max": 0.0, "in_flight": 0},
    "overlay":  {"count": 0, "errors": 0, "too_many": 0, "dur_ms_sum": 0.0, "dur_ms_max": 0.0, "in_flight": 0},
}


def obs_begin(kind: str) -> float:
    try:
        OBS[kind]["count"] += 1
        OBS[kind]["in_flight"] += 1
    except Exception:
        pass
    return time.perf_counter()


def obs_end(kind: str, t0: float, *, ok: bool) -> None:
    try:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        OBS[kind]["dur_ms_sum"] += dt_ms
        if dt_ms > OBS[kind]["dur_ms_max"]:
            OBS[kind]["dur_ms_max"] = dt_ms
        if not ok:
            OBS[kind]["errors"] += 1
    except Exception:
        pass
    finally:
        try:
            OBS[kind]["in_flight"] = max(0, int(OBS[kind]["in_flight"]) - 1)
        except Exception:
            pass


def obs_too_many(kind: str) -> None:
    try:
        OBS[kind]["too_many"] += 1
    except Exception:
        pass
