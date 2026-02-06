from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta


def test_market_gate_force_open_if_next_open_far(monkeypatch):
    """When market is closed and next open is far away, gate should allow collection."""
    monkeypatch.delenv('G6_FORCE_MARKET_OPEN', raising=False)
    monkeypatch.setenv('G6_FORCE_MARKET_OPEN_IF_NEXT_OPEN_GT_MINUTES', '120')

    mh = importlib.import_module('src.utils.market_hours')
    monkeypatch.setattr(mh, 'is_market_open', lambda **_: False)

    now = datetime.now(UTC)
    monkeypatch.setattr(mh, 'get_next_market_open', lambda **_: now + timedelta(hours=3))

    from src.collectors.modules.market_gate import evaluate_market_gate

    proceed, early = evaluate_market_gate(build_snapshots=False, metrics=None)
    assert proceed is True
    assert early is None


def test_market_gate_no_force_open_if_next_open_soon(monkeypatch):
    """If next open is soon, the conditional override should not engage."""
    monkeypatch.delenv('G6_FORCE_MARKET_OPEN', raising=False)
    monkeypatch.setenv('G6_FORCE_MARKET_OPEN_IF_NEXT_OPEN_GT_MINUTES', '120')

    mh = importlib.import_module('src.utils.market_hours')
    monkeypatch.setattr(mh, 'is_market_open', lambda **_: False)

    now = datetime.now(UTC)
    monkeypatch.setattr(mh, 'get_next_market_open', lambda **_: now + timedelta(minutes=60))

    from src.collectors.modules.market_gate import evaluate_market_gate

    proceed, early = evaluate_market_gate(build_snapshots=False, metrics=None)
    assert proceed is False
    assert isinstance(early, dict)
    assert early.get('status') == 'market_closed'


def test_orchestrator_gate_force_open_if_next_open_far(monkeypatch):
    """Loop-level market-hours skip should also honor the conditional override."""
    monkeypatch.delenv('G6_FORCE_MARKET_OPEN', raising=False)
    monkeypatch.setenv('G6_FORCE_MARKET_OPEN_IF_NEXT_OPEN_GT_MINUTES', '120')

    from src.orchestrator import gating

    monkeypatch.setattr(gating, 'is_market_open', lambda **_: False)
    monkeypatch.setattr(gating, 'get_next_market_open', lambda **_: datetime.now(UTC) + timedelta(hours=3))

    assert gating.should_skip_cycle_market_hours(True) is False
