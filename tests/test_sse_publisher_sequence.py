from __future__ import annotations

import os

BASE_STATUS = {
    "app": {"version": "1.0"},
    "indices": ["NIFTY", "BANKNIFTY"],
    "alerts": {"total": 1},
}


def test_sse_sequence_hello_full_update_heartbeat(monkeypatch):
    # Force enable SSE for the test runtime
    monkeypatch.setenv('G6_SSE_ENABLED', '1')
    monkeypatch.setenv('G6_SSE_HEARTBEAT_CYCLES', '2')  # faster heartbeat for test

    import importlib
    from scripts.summary.plugins import sse as sse_mod
    sse_mod = importlib.reload(sse_mod)
    SSEPublisher = sse_mod.SSEPublisher
    from scripts.summary.plugins.base import SummarySnapshot
    from scripts.summary.domain import build_domain_snapshot

    def make_snapshot(status: dict, cycle: int) -> SummarySnapshot:
        return SummarySnapshot(
            status=status,
            derived={},
            panels={},
            ts_read=0.0,
            ts_built=0.0,
            cycle=cycle,
            errors=[],
            model=None,
            domain=build_domain_snapshot(status, ts_read=0.0),
        )

    pub = SSEPublisher(diff=True)
    pub.setup({})

    # Cycle 1 -> expect hello + full_snapshot
    snap1 = make_snapshot(dict(BASE_STATUS), 1)
    pub.process(snap1)
    events = pub.events
    assert len(events) == 2, f"expected 2 events, got {len(events)}"
    assert events[0]['event'] == 'hello'
    assert events[1]['event'] == 'full_snapshot'

    # Cycle 2 (no change) -> no event yet (since heartbeat every 2 unchanged cycles)
    snap2 = make_snapshot(dict(BASE_STATUS), 2)
    pub.process(snap2)
    assert len(pub.events) == 2, "no new events expected before heartbeat interval"

    # Cycle 3 (still no change) -> heartbeat
    snap3 = make_snapshot(dict(BASE_STATUS), 3)
    pub.process(snap3)
    assert pub.events[-1]['event'] == 'heartbeat'

    # Cycle 4 (introduce change: alerts total increment) -> panel_update
    changed = dict(BASE_STATUS)
    changed['alerts'] = {"total": 2}
    snap4 = make_snapshot(changed, 4)
    pub.process(snap4)
    assert pub.events[-1]['event'] == 'panel_update'
    update_evt = pub.events[-1]
    updates = update_evt['data']['updates']
    keys = {u['key'] for u in updates}
    assert 'alerts' in keys, "alerts panel should be in update set"

    # Cycle 5 + 6 no further changes -> next heartbeat on cycle 6
    snap5 = make_snapshot(changed, 5)
    pub.process(snap5)
    snap6 = make_snapshot(changed, 6)
    pub.process(snap6)
    assert pub.events[-1]['event'] == 'heartbeat', "expected heartbeat after two unchanged cycles"
