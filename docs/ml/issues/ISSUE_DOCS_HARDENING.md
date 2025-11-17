# Issue: Documentation Hardening & Alignment

## Summary
Consolidate API + performance + ops docs to reduce duplication and ensure new features are discoverable.

## Tasks
- Expand `ENSEMBLE_API.md` with full detail schema once implemented.
- Add metrics table & examples (`curl /metrics | grep g6_forecast_latency_ms`).
- Reference new env vars (cache TTL, MAX, file cache TTL, metrics flag).
- Include versioning & deprecation guarantees summary.
- Add quick “Common Integration Patterns” section: polling, diffing snapshots, path visualization.
- Link Phase 9 issues at bottom for traceability.

## Acceptance Criteria
- Single source of truth for forecast schema (no stale port numbers, 9500 confirmed).
- All new env vars documented.
- Example responses updated & validated against test fixture.

## Risks
Merge conflicts: coordinate edits with issue completion sequence.
