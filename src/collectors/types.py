"""Collector result type contracts (Phase 7).

Defines lightweight TypedDicts for expiry and index result structures emitted by
pipeline collectors. These provide static clarity while preserving the existing
runtime dict shape (no serialization changes). Downstream code may gradually
adopt these types for improved maintainability.

Guiding constraints:
- Keys mirror existing pipeline return structure.
- Optional fields kept optional to avoid forcing legacy paths to populate them.
- Runtime validation intentionally light; tests rely on shape presence only.

Terminology Note:
- "options" = option instruments (e.g., NIFTY 24500 CE, NIFTY 24500 PE)
- "strikes" = unique strike price levels (e.g., 24500, 24550)
- For each strike, there are typically 2 options: 1 CE + 1 PE
- Example: 10 strikes → 20 options (10 CE + 10 PE)
"""
from __future__ import annotations

from typing import TypedDict, NotRequired, Any

class ExpiryResult(TypedDict, total=False):
    rule: str
    status: str  # OK | EMPTY | PARTIAL
    options: int  # Count of option instruments (CE + PE), not strike price levels
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
    option_count: int  # Total option instruments across all expiries
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

# Phase 7: Unified type contracts for index_processor module
class StrikeUniverseResult(TypedDict, total=False):
    """Result from strike universe building (adaptive or fixed selection)."""
    strikes: list[float]
    meta: dict[str, Any]

class IndexProcessResult(TypedDict, total=False):
    """Result from processing a single index through unified_collectors path."""
    human_block: NotRequired[str | None]
    indices_struct_entry: NotRequired[dict[str, Any] | None]
    summary_rows_entry: NotRequired[dict[str, Any] | None]
    overall_legs: int
    overall_fails: int

# Type aliases for gradual migration
ExpiryDetail = dict[str, Any]  # Dynamic expiry details; can be narrowed later

# Explicit exports
__all__ = [
    "ExpiryResult",
    "IndexResult",
    "PipelineReturn",
    "StrikeUniverseResult",
    "IndexProcessResult",
    "ExpiryDetail",
]

"""
Usage example:

    # Pipeline module
    expiries_out: list[ExpiryResult] = []
    indices_struct: list[IndexResult] = []
    
    # Index processor module
    from src.collectors.types import StrikeUniverseResult, IndexProcessResult
    su_result: StrikeUniverseResult = build_strike_universe(...)
    proc_result: IndexProcessResult = {...}

Serialization remains identical: structures are plain dicts at runtime.
"""
