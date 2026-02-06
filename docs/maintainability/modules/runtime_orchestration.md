# Runtime & Orchestration

## Scope
Bootstrapping, lifecycle, interval loop management, graceful shutdown, feature toggles.

## Primary code
- `src/orchestrator/`
- `src/unified_main.py`
- `scripts/run_orchestrator_loop.py`

## Signals (from generated stats)
- `src/orchestrator`: ~6.6k LOC; ~76 occurrences of `except Exception`; notable `type: ignore` usage.

## Maintainability risks
- Multiple entrypoints (scripts + module entry) can drift.
- Feature flags and bootstrap concerns can leak into business logic.

## Improvements
- Define one canonical “run loop” API and have scripts delegate to it.
- Make orchestration depend on a small collector interface (run one cycle / run N cycles).
- Make shutdown/interrupt policy explicit and tested (what gets flushed, what gets skipped).
