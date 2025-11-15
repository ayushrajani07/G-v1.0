# Phase 1: Exception Handling Audit Plan (Storage First)

Date: 2025-11-15
Baseline source: `audit/exceptions_baseline.txt`

---

## Baseline Summary

- Total `except Exception:` occurrences: 3041
- Top packages by occurrences (tsv excerpt from `audit/exceptions_by_top_package.tsv`):
  - collectors	771
  - metrics	466
  - web	358
  - orchestrator	355
  - utils	306
  - storage	48

Full breakdowns:
- `audit/exceptions_by_top_package.tsv`
- `audit/exceptions_by_file.tsv`
- `audit/exceptions_storage_by_file.tsv`

---

## Storage Module Priorities

Refactor in this order (highest offenders first):

1. `src/storage/csvio/backends/atomic_fs.py` — 9
2. `src/storage/influx_sink.py` — 8
3. `src/storage/csv_aggregator.py` — 7
4. `src/storage/csv_batcher.py` — 5
5. `src/storage/retention.py` — 4
6. `src/storage/csvio/writer_thread.py` — 4
7. `src/storage/parquet_sink.py` — 3
8. `src/storage/file_buffer_manager.py` — 3
9. `src/storage/csvio/backends/filesystem.py` — 2
10. `src/storage/csv_utils.py` — 1
11. `src/storage/influx_buffer_manager.py` — 1
12. `src/storage/influx_connection_pool.py` — 1

---

## Refactoring Pattern

- Replace broad `except Exception:` with specific exceptions (e.g., `OSError`, `IOError`, `PermissionError`, client-specific errors)
- Add targeted retries around transient I/O/network failures
- Preserve metrics and structured logs, use parameterized logging
- Re-raise unexpected exceptions after cleanup/metrics

Example:
```python
try:
    write_csv_atomic(path, data)
except PermissionError as e:
    logger.error("Permission denied: %s", e, exc_info=True)
    raise
except (OSError, IOError) as e:
    logger.warning("Write failed, will retry: %s", e, exc_info=True)
    raise  # wrap with retry decorator at call site
except Exception as e:
    logger.critical("Unexpected storage error: %s", e, exc_info=True)
    raise
```

---

## Definition of Done (per file)

- All broad catches replaced or justified with comments
- Tests updated/added for failure modes (permission, I/O, network)
- Metrics unchanged or improved; log volume acceptable under failure
- Local run: `pytest -q tests/storage -k <module> -v`

---

## Validation & Rollout

- Run full suite in parallel after each file or pair of files:
```powershell
. .venv\Scripts\Activate.ps1
python -m pytest -n auto
```
- Gate rollout behind `G6_NEW_EXCEPTION_HANDLING` if needed for safe deploy
- Coordinate with ops for monitoring thresholds and alert noise

---

## Ownership & Scheduling

- Module owners: TBD
- Cadence: 2–3 files/day; review and merge daily
- Daily standup: track exceptions count delta, test results, and fallout
