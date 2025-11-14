"""Scheduling helpers for steady cadence loops.

Provides monotonic-time based sleep helpers to avoid drift and wall-clock
adjustments affecting periodic loops. Supports optional jitter to reduce
cross-process synchronization.
"""
from __future__ import annotations

import random
import time
from typing import Tuple

__all__ = [
    "compute_sleep_for",
    "next_deadline",
]


def compute_sleep_for(start_monotonic: float, interval: float, *, now_fn=time.monotonic, jitter_ms: float = 0.0) -> float:
    """Compute remaining sleep time to honor a fixed interval from a start tick.

    Uses monotonic clock to avoid wall-clock jumps. Optional jitter (milliseconds)
    is subtracted randomly from the sleep time (bounded to [0, sleep_for]).
    """
    now = float(now_fn())
    deadline = float(start_monotonic) + float(interval)
    sleep_for = max(0.0, deadline - now)
    if jitter_ms > 0.0 and sleep_for > 0.0:
        jitter_s = random.uniform(0.0, jitter_ms) / 1000.0
        sleep_for = max(0.0, sleep_for - min(jitter_s, sleep_for))
    return sleep_for


def next_deadline(prev_deadline: float | None, interval: float, *, now_fn=time.monotonic) -> Tuple[float, float]:
    """Return (deadline, sleep_for) based on previous deadline and interval.

    If prev_deadline is None, schedule first deadline at now + interval. If
    previous deadline is in the past, compute sleep as 0 and set deadline to
    the nearest future tick (one interval ahead of now).
    """
    now = float(now_fn())
    if prev_deadline is None:
        dl = now + float(interval)
        return dl, max(0.0, float(interval))
    # compute remaining vs previous deadline
    remain = prev_deadline - now
    if remain <= 0.0:
        # missed the deadline; schedule next interval from current time
        return now + float(interval), 0.0
    return prev_deadline, remain
