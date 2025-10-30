from __future__ import annotations

import time
import pytest

from src.utils.resilience import retry, fallback, timeout


def test_retry_succeeds_after_failures():
    calls = {"n": 0}

    @retry(max_attempts=3, delay=0.01, backoff_factor=1.0, jitter=False)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return 42

    assert flaky() == 42
    assert calls["n"] == 3


def test_fallback_returns_default():
    @fallback(default_value=123)
    def bad():
        raise RuntimeError("nope")

    assert bad() == 123


def test_timeout_raises():
    @timeout(0.05)
    def slow():
        time.sleep(0.2)
        return "done"

    with pytest.raises(TimeoutError):
        slow()
