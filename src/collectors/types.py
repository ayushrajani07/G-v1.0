"""Collector result type contracts (Phase 7).

Defines lightweight TypedDicts for expiry and index result structures emitted by
pipeline collectors. These provide static clarity while preserving the existing
runtime dict shape (no serialization changes). Downstream code may gradually
adopt these types for improved maintainability.

Guiding constraints:
- Keys mirror existing pipeline return structure.
- Optional fields kept optional to avoid forcing legacy paths to populate them.
- Runtime validation intentionally light; tests rely on shape presence only.
"""
from __future__ import annotations

from typing import TypedDict, NotRequired, Any

class ExpiryResult(TypedDict, total=False):
    rule: str
    status: str  # OK | EMPTY | PARTIAL
    options: int
    strike_coverage: NotRequired[float | None]
    field_coverage: NotRequired[float | None]
    partial_reason: NotRequired[str | None]
    synthetic_quotes: NotRequired[bool]
    failed: NotRequired[bool]
    reason: NotRequired[str]

class IndexResult(TypedDict, total=False):
    index: str
    attempts: int
    failures: int
    option_count: int
    status: str  # OK | EMPTY
    expiries: list[ExpiryResult]
    elapsed_s: float
    strike_coverage_avg: NotRequired[float | None]
    field_coverage_avg: NotRequired[float | None]

class PipelineReturn(TypedDict, total=False):
    status: str
    indices_processed: int
    have_raw: bool
    snapshots: Any | None
    snapshot_count: int
    indices: list[IndexResult]
    partial_reason_totals: dict[str,int]
    snapshot_summary: NotRequired[dict[str, Any] | None]
    partial_reason_groups: NotRequired[dict[str, Any]]
    partial_reason_order: NotRequired[list[str]]
    partial_reason_group_order: NotRequired[list[str]]
    diagnostics: NotRequired[dict[str, Any]]
"""
Usage example (within pipeline):

    expiries_out: list[ExpiryResult] = []
    indices_struct: list[IndexResult] = []

Serialization remains identical: structures are plain dicts at runtime.
"""
