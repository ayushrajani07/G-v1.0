"""Shared phase result + diagnostics containers.

Phase 3 / PR3.1 introduces lightweight, serializable models for capturing
per-phase execution outcomes and roll-up diagnostics without forcing a runtime
schema change on existing callers.

These models are intentionally small:
- Used by the pipeline executor to compute a stable summary.
- Can be adopted by individual phase functions later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


PhaseOutcome = Literal[
    "ok",
    "abort",
    "recoverable",
    "recoverable_exhausted",
    "fatal",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class PhaseRun:
    phase: str
    final_outcome: str
    attempts: int
    duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "final_outcome": self.final_outcome,
            "attempts": int(self.attempts),
            "duration_ms": float(self.duration_ms),
        }


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    phases_total: int
    phases_ok: int
    phases_error: int
    phases_with_retries: int
    retry_enabled: bool
    error_outcomes: dict[str, int]
    aborted_early: bool
    fatal: bool
    recoverable_exhausted: bool

    @classmethod
    def from_runs(cls, runs: list[PhaseRun], *, retry_enabled: bool) -> "PipelineSummary":
        ok_count = sum(1 for r in runs if r.final_outcome == "ok")
        errored = [r for r in runs if r.final_outcome != "ok"]
        retries = [r for r in runs if int(r.attempts) > 1]
        distinct_err = {r.final_outcome for r in errored}
        err_counts = {o: sum(1 for r in errored if r.final_outcome == o) for o in distinct_err}

        return cls(
            phases_total=len(runs),
            phases_ok=ok_count,
            phases_error=len(errored),
            phases_with_retries=len(retries),
            retry_enabled=bool(retry_enabled),
            error_outcomes=err_counts,
            aborted_early=any(r.final_outcome == "abort" for r in runs),
            fatal=any(r.final_outcome == "fatal" for r in runs),
            recoverable_exhausted=any(r.final_outcome == "recoverable_exhausted" for r in runs),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "phases_total": int(self.phases_total),
            "phases_ok": int(self.phases_ok),
            "phases_error": int(self.phases_error),
            "phases_with_retries": int(self.phases_with_retries),
            "retry_enabled": bool(self.retry_enabled),
            "error_outcomes": dict(self.error_outcomes),
            "aborted_early": bool(self.aborted_early),
            "fatal": bool(self.fatal),
            "recoverable_exhausted": bool(self.recoverable_exhausted),
        }


__all__ = ["PhaseOutcome", "PhaseRun", "PipelineSummary"]
