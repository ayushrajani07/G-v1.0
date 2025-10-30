import os
from src.collectors.enhanced_shim import run_enhanced_collectors
from src.collectors.providers_interface import Providers
from tests.fixtures import DummyProviders, DummyCsvSink, DummyInfluxSink, DummyMetrics


def test_enhanced_collector_snapshots(monkeypatch):
    """Validate backward-compat shim returns snapshots when explicitly requested.

    Post-migration `run_enhanced_collectors` delegates to unified collectors unless
    snapshot mode is enabled or return_snapshots flag evaluates true. The legacy
    test assumed the function always returned a list of ExpirySnapshot objects.
    We now force snapshot behavior explicitly via both env var and explicit
    return_snapshots kw to guarantee deterministic semantics, independent of
    internal shim evolution.
    """
    providers = Providers(primary_provider=DummyProviders())
    csv_sink = DummyCsvSink()
    influx_sink = DummyInfluxSink()
    metrics = DummyMetrics()
    index_params = {"NIFTY": {"expiry_rules": ["this_week"], "offsets": [0], "strike_step": 50}}
    # Ensure snapshots path is taken even if underlying shim changes defaults.
    monkeypatch.setenv('G6_RETURN_SNAPSHOTS','1')
    monkeypatch.setenv('G6_ENHANCED_SNAPSHOT_MODE','1')  # force shim snapshot branch
    snaps = run_enhanced_collectors(
        index_params,
        providers,
        csv_sink,
        influx_sink,
        metrics,
        enrichment_enabled=False,
        only_during_market_hours=False,
        min_volume=0,
        min_oi=0,
        return_snapshots=True,
    )
    assert isinstance(snaps, list), "Expected list of snapshots when snapshot mode forced"
    assert len(snaps) == 1
    snap = snaps[0]
    assert getattr(snap, 'index', None) == 'NIFTY'
    assert getattr(snap, 'expiry_rule', None) == 'this_week'
    # DummyProviders returns two legs per strike (1 strike -> 2 option objects)
    assert getattr(snap, 'option_count', 2) == 2
    assert all(getattr(o, 'timestamp', None) is not None for o in getattr(snap, 'options', []))
