from __future__ import annotations

from src.metrics.registry import get_registry


def test_get_registry_reset_returns_fresh_instance() -> None:
    r1 = get_registry(reset=True)
    r2 = get_registry(reset=True)
    assert r1 is not r2

    # After a reset, the singleton should be the latest instance.
    r3 = get_registry(reset=False)
    assert r3 is r2
