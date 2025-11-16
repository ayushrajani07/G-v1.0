# CycleEnvSettings

A lightweight per-cycle snapshot of frequently accessed `G6_*` environment
flags used in the collectors hot path. It complements `CollectorSettings`
(which captures longer-lived configuration and thresholds) by focusing on
volatile presentation and abort / outage control knobs.

## Goals

- Eliminate repeated `os.environ` and adapter lookups inside the cycle loop.
- Provide typed, lower‑cased, normalized fields (booleans, ints, enums).
- Clarify precedence: when both `CollectorSettings` and env provide values for
  provider outage controls, the settings object wins.
- Improve testability: unit tests can assert parsing and precedence without
  invoking the full collection loop.

## Fields

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| refactor_debug | bool | `G6_COLLECTOR_REFACTOR_DEBUG` | Enables verbose refactor diagnostics (legacy). |
| single_header_mode | bool | `G6_SINGLE_HEADER_MODE` | Forces a single banner emission and enables merged/single phase timing. |
| banner_debug | bool | `G6_BANNER_DEBUG` | Emits debug lines when banners are suppressed. |
| daily_header_every_cycle | bool | `G6_DAILY_HEADER_EVERY_CYCLE` | Re‑emit daily banner every cycle regardless of suppression flags. |
| disable_repeat_banners | bool | `G6_DISABLE_REPEAT_BANNERS` | Suppresses banner after first emission for the day (unless forced). |
| compact_banners | bool | `G6_COMPACT_BANNERS` | Switches to single‑line banner format. |
| enable_data_quality | bool | `G6_ENABLE_DATA_QUALITY` | Enables data quality checks (index/option/expiry consistency). |
| disable_pretty_cycle | bool | `G6_DISABLE_PRETTY_CYCLE` | Forces raw cycle output (machine line only). |
| cycle_output | str | `G6_CYCLE_OUTPUT` | `pretty` | `raw` | `both` selection (ignored if disable_pretty_cycle). |
| cycle_style | str | `G6_CYCLE_STYLE` | `legacy` or `readable` formatting function set. |
| stale_write_mode | str | `G6_STALE_WRITE_MODE` | `mark` (annotate) or `abort` (process exit after threshold). |
| stale_abort_cycles | int | `G6_STALE_ABORT_CYCLES` | Consecutive stale cycle threshold when `abort` mode. |
| provider_outage_threshold | int | settings or `G6_PROVIDER_OUTAGE_THRESHOLD` | Minimum consecutive empty cycles per index to call outage. |
| provider_outage_log_every | int | settings or `G6_PROVIDER_OUTAGE_LOG_EVERY` | Throttle interval for outage error log spam. |

## Precedence Rules

1. Provider outage threshold / log_every come first from `CollectorSettings`
   when available and >0; otherwise fall back to environment values.
2. `disable_pretty_cycle` overrides `cycle_output` by forcing raw mode.
3. `single_header_mode` implicitly aligns phase timing consolidation at
   import time (legacy globals retained) but banner emission uses the snapshot.
4. All string fields are normalized to lowercase; booleans accept: `1 true yes on`.

## Usage Pattern

Inside `run_unified_collectors`:
```python
cycle_env = CycleEnvSettings.from_env(collector_settings=_collector_settings)
# use cycle_env.single_header_mode, cycle_env.cycle_output, etc.
```
A legacy `_env_snapshot` dict is still populated for backward compatibility
with tests that probe specific keys; new code should prefer attributes.

## Testing Strategy

`tests/test_cycle_env_settings.py` covers:
- Parsing & normalization (mixed‑case values).
- Precedence of `CollectorSettings` for outage controls.
- Defaults when no env vars are set.

Consider adding integration tests capturing log patterns for banner suppression
if future refactors change formatting logic.

## Extension Guidelines

- Add new per‑cycle flags here if they are read >2 times inside the hot path.
- Avoid storing large / complex objects; keep this strictly to primitive types.
- For multi‑cycle cumulative counters prefer the metrics registry or a process‑level global.

## Future Opportunities

- Introduce a `ProcessRuntimeFlags` companion for import‑time / process‑scoped
  toggles (phase timing merge, global aggregation) to further isolate concerns.
- Emit a structured JSON snapshot (behind a flag) for external diagnostics.

---
_Last updated: 2025-11-11_
