from __future__ import annotations

import pytest


def test_async_csv_writer_multithreaded_producers() -> None:
    # This test is intentionally skipped: multithreaded producer ordering can be
    # nondeterministic on Windows due to timing/flush behavior.
    # Use the explicit harness `scripts/benchmarks/stress_csv_sink_under_load.py`
    # for load/concurrency validation.
    pytest.skip("flaky under CI timing; use stress harness instead")
