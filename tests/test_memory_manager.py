from __future__ import annotations

import gc
from types import SimpleNamespace

import pytest

from src.utils.memory_manager import MemoryManager


class _DummyGauge:
    def __init__(self) -> None:
        self.value = None

    def set(self, v: float) -> None:
        self.value = v


class _DummyMetrics:
    def __init__(self) -> None:
        self.memory_usage_mb = _DummyGauge()


class _DummyProc:
    def __init__(self, rss_bytes: int) -> None:
        self._rss = int(rss_bytes)

    def memory_info(self):
        return SimpleNamespace(rss=self._rss)


def test_emergency_cleanup_invokes_purge_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    mm = MemoryManager()

    called: list[str] = []

    def purge_a() -> None:
        called.append("a")

    def purge_b() -> None:
        called.append("b")

    mm.register_cache("a", purge_fn=purge_a)
    mm.register_cache("b", purge_fn=purge_b)
    mm.register_cache("no_purge", purge_fn=None)

    monkeypatch.setattr(gc, "collect", lambda *a, **k: 0)

    attempted = mm.emergency_cleanup(reason="unit-test")
    assert attempted == 2
    assert set(called) == {"a", "b"}


def test_post_cycle_cleanup_updates_metrics_with_rss(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure env knobs are read from scratch.
    monkeypatch.setenv("G6_MEMORY_GC_INTERVAL_SEC", "0")
    monkeypatch.setenv("G6_MEMORY_MINOR_GC_EACH_CYCLE", "1")

    mm = MemoryManager()
    mm._proc = _DummyProc(rss_bytes=123 * 1024 * 1024)  # type: ignore[attr-defined]

    metrics = _DummyMetrics()

    # Avoid real GC work / nondeterminism.
    monkeypatch.setattr(gc, "collect", lambda *a, **k: 0)

    mm.post_cycle_cleanup(aggressive=False, metrics=metrics)
    assert metrics.memory_usage_mb.value == pytest.approx(123.0, rel=1e-6)

    stats = mm.get_stats()
    assert stats["rss_mb"] == pytest.approx(123.0, rel=1e-6)
    assert stats["gc_last_duration_ms"] is not None
