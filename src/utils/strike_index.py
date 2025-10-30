"""StrikeIndex helper (R2 performance optimization).

Provides fast membership, diff, and descriptive statistics for strike ladders.
Uses scaled-integer representation to avoid repeated float rounding & tolerance checks.

Design Goals:
- O(1) membership checks
- Cheap diff between requested & realized sets
- Central place to extend adaptive logic (future: dynamic depth scaling)
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["StrikeIndex", "build_strike_index"]

SCALE = 100  # two decimal precision scaling
TOL_UNITS = 1  # <=1 unit => <=0.01 actual difference considered equal

@dataclass(slots=True)
class StrikeIndex:
    original: Sequence[float]
    sorted: list[float]
    scaled_set: set[int]
    min_step: float

    def contains(self, value: float) -> bool:
        try:
            sv = int(round(float(value) * SCALE))
        except Exception:
            return False
        if sv in self.scaled_set:
            return True
        # tolerant check (+/-1 unit) for small float jitter
        return (sv - 1 in self.scaled_set) or (sv + 1 in self.scaled_set)

    def diff(self, realized: Iterable[float]) -> dict[str, list[float]]:
        """Return missing and extra strikes relative to realized list."""
        def _to_scaled(tok: float) -> int | None:
            try:
                return int(round(float(tok) * SCALE))
            except Exception:
                return None
        r_scaled: set[int] = set()
        for v in realized:
            sv = _to_scaled(v)
            if sv is not None:
                r_scaled.add(sv)
        missing_scaled = [s for s in self.scaled_set if s not in r_scaled]
        extra_scaled = [s for s in r_scaled if s not in self.scaled_set]
        # Convert back (sorted for stable output)
        missing = sorted({ms / SCALE for ms in missing_scaled})
        extra = sorted({es / SCALE for es in extra_scaled})
        return {"missing": missing, "extra": extra}

    def describe(self, sample: int = 6) -> dict[str, Any]:
        strikes = self.sorted
        n = len(strikes)
        if n == 0:
            return {"count": 0, "min": None, "max": None, "step": 0, "sample": []}
        # step heuristic: min positive diff
        diffs = [b - a for a, b in zip(strikes, strikes[1:], strict=False) if b - a > 0]
        step = min(diffs) if diffs else 0
        if n <= sample:
            samp = [f"{s:.0f}" for s in strikes]
        else:
            head = [f"{s:.0f}" for s in strikes[:2]]
            mid = [f"{strikes[n//2]:.0f}"]
            tail = [f"{s:.0f}" for s in strikes[-2:]]
            samp = head + mid + tail
        return {
            "count": n,
            "min": strikes[0],
            "max": strikes[-1],
            "step": step,
            "sample": samp,
            "min_step": self.min_step,
        }

    def realized_coverage(self, realized: Iterable[float]) -> float:
        def _to_scaled_positive(tok: float) -> int | None:
            try:
                fv = float(tok)
                if fv > 0:
                    return int(round(fv * SCALE))
            except Exception:
                return None
            return None
        r_scaled: set[int] = set()
        for v in realized:
            sv = _to_scaled_positive(v)
            if sv is not None:
                r_scaled.add(sv)
        if not self.scaled_set:
            return 0.0
        matched = sum(1 for s in self.scaled_set if s in r_scaled or (s-1 in r_scaled) or (s+1 in r_scaled))
        return matched / len(self.scaled_set)


def build_strike_index(strikes: Sequence[float]) -> StrikeIndex:
    def _safe_float(tok: float) -> float | None:
        try:
            fv = float(tok)
            return fv if fv > 0 else None
        except Exception:
            return None
    filtered: list[float] = []
    for s in strikes:
        fv = _safe_float(s)
        if fv is not None:
            filtered.append(fv)
    filtered.sort()
    scaled_set = {int(round(s * SCALE)) for s in filtered}
    # Precompute min step
    diffs = [b - a for a, b in zip(filtered, filtered[1:], strict=False) if b - a > 0]
    min_step = min(diffs) if diffs else 0
    return StrikeIndex(original=strikes, sorted=filtered, scaled_set=scaled_set, min_step=min_step)
