# Persistence & Data Access

## Scope
CSV/Influx persistence, retention, readback/query surfaces, column-store integration.

## Primary code
- `src/storage/`
- `src/data_access/`
- `src/column_store/` (if used)

## Signals (from generated stats)
- `src/storage`: ~6.9k LOC; ~84 `except Exception` occurrences.

## Hotspot files (good first refactor targets)
- `src/storage/csv_sink.py` (very large)

## Maintainability risks
- IO-heavy code tends to accumulate “catch-all and continue” patterns.
- Monolith sinks can be hard to evolve without regressions.

## Improvements
- Split sinks by responsibility: formatting, buffering, filesystem IO, integrity/atomicity.
- Make failure policy explicit (drop vs retry vs fail-cycle), shared with collectors.
- Ensure all writes are traceable (structured error records + metrics).
