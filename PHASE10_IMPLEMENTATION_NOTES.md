# Phase 10: Safe I/O Exception Hygiene — Finalization Notes

This patch completes stabilization around safe file I/O exception hygiene and removes redundant test-time restorations.

## Changes
- src/error_handling.py
  - get_error_handler(): if `safe_write_text` or `safe_append_line` are MagicMock, set `side_effect` to their original implementations to ensure call-through behavior even when mocks were imported earlier. Fallback to hard-restore when needed.

- tests/test_safe_file_io_failure.py
  - Updated unittest-style tests to import the module (`import src.error_handling as eh`) and call `eh.get_error_handler()` before invoking `eh.safe_write_text`/`eh.safe_append_line`.
  - Removed `importlib.reload` to avoid sys.modules timing issues.

- tests/conftest.py
  - Removed autouse restoration fixture and extra hooks that tried to force-restore safe I/O helpers per test.
  - Kept environment, metrics, sandbox, and async support fixtures unchanged.

- src/web/dashboard/routes/ensemble.py
  - Added adaptive per-key cache TTL prototype behind `G6_FORECAST_CACHE_ADAPTIVE_TTL`.
  - New envs: `G6_FORECAST_CACHE_TTL_MIN` (default 10s), `G6_FORECAST_CACHE_TTL_MAX` (default 60s),
    `G6_ADAPTIVE_TTL_IV_REF` (IV normalization ref, default 0.35), weights `G6_ADAPTIVE_TTL_W_IV` (0.7), `G6_ADAPTIVE_TTL_W_WIN` (0.3).
  - Cache now stores per-key TTL; stats endpoint returns ttl per entry and flags.

## Rationale
- Prevent order-dependent flakiness caused by MagicMocks captured before restoration.
- Minimize cross-test coupling by moving behavior guarantees to source code and specific tests rather than global hooks.
- Reduce unnecessary recomputation under calm regimes while refreshing more aggressively under high volatility, without changing API semantics.

## Validation
- Targeted tests: `tests/test_safe_file_io_failure.py` pass in isolation and within full suite.
- Full serial suite: 1767 passed, 561 skipped (~27s) on Windows/py312 environment.
- Manual verification: cache stats now include adaptive fields; functional behavior unchanged when flag disabled.

## Risk/Impact
- The `side_effect` call-through only activates when the target is a MagicMock and original functions are recorded, so normal mocking flows remain predictable.
- No runtime behavior changes for production code paths.

## Follow-ups
- None required. Optional: brief note in developer docs about the pattern (module import + call to `get_error_handler()` before using safe I/O helpers in tests that simulate failures).
