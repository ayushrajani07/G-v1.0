from __future__ import annotations

import os

from src.orchestrator.context import RuntimeContext
from src.orchestrator.loop import run_loop
from src.utils.exceptions import RetryError


def test_run_loop_does_not_terminate_on_retry_error(monkeypatch):
    # Avoid sleeping in test even if backoff is enabled by defaults.
    monkeypatch.setenv("G6_LOOP_ERROR_BACKOFF_BASE_SEC", "0")
    monkeypatch.setenv("G6_LOOP_ERROR_BACKOFF_MAX_SEC", "0")

    ctx = RuntimeContext(config={})

    def cycle_fn(c: RuntimeContext) -> None:
        # Simulate connectivity loss during provider calls.
        c.shutdown = True
        raise RetryError("HTTPSConnectionPool timed out")

    # Should return normally (i.e., swallow RetryError) rather than raising.
    run_loop(ctx, cycle_fn=cycle_fn, interval=0.0)
