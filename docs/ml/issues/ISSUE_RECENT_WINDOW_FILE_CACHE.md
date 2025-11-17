# Issue: Add File-Level Recent Window Cache

## Summary
Implement a lightweight, mtime-aware cache for the recent TP window loaded from today’s CSV to reduce disk I/O and repeated parsing when `recent_window_size > 0`.

## Motivation
Repeated CSV parsing is wasteful under higher QPS; caching improves latency and reduces CPU usage.

## Scope
- Internal caching only (no persistence across restarts).
- Exposed stats merged into `/api/ml/ensemble/cache/stats` (hit/miss for file window).

## Requirements
- Environment variables:
  - `G6_RECENT_FILE_CACHE_TTL` (seconds, default `60`)
  - `G6_RECENT_FILE_CACHE_MAX_SIZE` (default `50`) for multi-index or different window sizes.
- Cache key includes: `(index, date_str, window_size)`; if a larger window requested and a smaller cached list exists, reuse list and slice last N.
- Invalidate if file mtime changes or TTL exceeded.
- Stats tracked: `recent_file_cache_hits`, `recent_file_cache_misses`, `recent_file_cache_current_entries`.
- Add these to `/cache/stats` response under `recent_file_cache`.

## Implementation Outline
1. Introduce module-level dict storing `{key: {rows, mtime, ts}}`.
2. Wrap existing `_load_recent_window` logic with cache lookup.
3. On lookup: if entry present, TTL valid, mtime matches — hit; else reload.
4. Purge oldest entry if size exceeds `MAX_SIZE`.
5. Add counters + expose in stats endpoint.

## Acceptance Criteria
- Cache reduces subsequent identical recent window loads to zero disk reads (observable via debug log or timing drop).
- Stats reflect hits/misses accurately in manual tests.
- Docs updated with new env vars and stats section.

## Test Plan
- Unit: simulate two sequential calls with same params; expect a hit count increment.
- Modify file mtime (touch/append) and ensure invalidation occurs.
- TTL expiry test: set TTL to 1s, wait, re-request → miss.

## Risks & Mitigation
| Risk | Mitigation |
|------|------------|
| Stale data after file rotation | Mtime check forces reload |
| Memory growth | MAX_SIZE + eviction policy |
| Concurrency race | Use simple lock for mutation |

## Deliverables
- Code in router file or a helper module (e.g., `recent_window_cache.py`).
- Tests: `tests/test_recent_file_cache.py`.
- Docs: `ENSEMBLE_API.md` + changelog.
