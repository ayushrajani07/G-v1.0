# Collection Pipeline

## Scope
Cycle execution across indices, fetching, enrichment, validation, persistence triggers, event emission.

## Primary code
- `src/collectors/` (+ smaller `src/collector/`)
- Supporting: `src/events/`, `src/filters/`, `src/bus/`, `src/streaming/`

## Signals (from generated stats)
- `src/collectors`: ~18.1k LOC; **~489** `except Exception` occurrences; notable `type: ignore` usage.

## Hotspot files (good first refactor targets)
- `src/collectors/modules/index_processor.py` (high catch-all density)
- `src/collectors/pipeline/executor.py` (high catch-all density)
- `src/collectors/modules/expiry_processor.py`
- `src/collectors/modules/expiry_pipeline.py`
- `src/collectors/pipeline/phases.py`
- `src/collectors/unified_collectors.py` (large / central)

## Maintainability risks
- High catch-all exception density can hide bugs and makes reasoning about failure modes hard.
- Pipeline stages can become “god functions” if stage boundaries aren’t explicit.
- Hard-to-test flows when IO (provider/storage) is deeply mixed with business rules.

## Improvements
- Introduce a small set of *typed stage errors* and standard handling (retry/drop/fail-cycle).
- Make stage interfaces explicit (inputs/outputs) so stages can be unit-tested.
- Extract “cycle context” object (immutable where possible): config snapshot, timings, enabled features.
- Add module-level doc: golden path of a cycle and invariants (what must always be emitted).
