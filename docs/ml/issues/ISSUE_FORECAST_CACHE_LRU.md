# Issue: Add LRU Bound to Forecast Cache

## Summary
Extend existing in-memory forecast cache with configurable max entries and eviction stats.

## Motivation
Prevent unbounded growth under diverse parameter combinations; surface occupancy for tuning.

## Requirements
- Env vars:
  - `G6_FORECAST_CACHE_MAX` (default `500`).
- Eviction strategy: remove oldest access (LRU) when inserting new entry over limit.
- Stats additions in `/cache/stats`: `evictions`, `max_size`.
- Maintain existing TTL behavior; eviction independent of expiry.

## Implementation Outline
1. Track access order (e.g., OrderedDict or manual list) guarded by lock.
2. On get: mark key as most recently used.
3. On put: if size >= max, evict LRU then insert.
4. Increment `evictions` counter.
5. Update stats endpoint.

## Acceptance Criteria
- Evictions occur once size exceeds max; `evictions` increments.
- Access reorders entries correctly (recently accessed not evicted prematurely).
- No performance regression (O(1) operations). Use basic Python structures.

## Test Plan
- Insert > max entries; assert size == max and evictions > 0.
- Access middle entry then insert new entries until eviction; confirm accessed entry retained.

## Risks
Minimal; simple data structure choice. Ensure thread safety with lock.
