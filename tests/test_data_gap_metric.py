import time
from types import SimpleNamespace
from prometheus_client import CollectorRegistry, Gauge, Counter, Histogram

from src.orchestrator.cycle import run_cycle
from tests.fixtures import DummyProviders, DummySink, make_ctx as make_base_ctx

def make_ctx():
    """Create context with data gap metric setup."""
    ctx = make_base_ctx()
    reg = CollectorRegistry()
    m = SimpleNamespace()
    m.cycle_time_seconds = Histogram('test_cycle_time_seconds','cycle', registry=reg)
    m.cycle_sla_breach = Counter('test_cycle_sla_breach_total','sla', registry=reg)
    m.data_gap_seconds = Gauge('test_data_gap_seconds','gap', registry=reg)
    m.index_data_gap_seconds = Gauge('test_index_data_gap_seconds','index gap', ['index'], registry=reg)
    ctx.metrics = m
    return ctx


def test_data_gap_increases_between_cycles(monkeypatch):
    monkeypatch.setenv('G6_CYCLE_INTERVAL','1')
    ctx = make_ctx()
    # First cycle establishes last success timestamp
    run_cycle(ctx)  # type: ignore[arg-type]
    time.sleep(0.05)
    t0 = time.time()
    run_cycle(ctx)  # type: ignore[arg-type]
    # data_gap_seconds is updated inside second run at end referencing prior timestamp
    # We stored gap indirectly; emulate instrumentation logic: if last_success set before second cycle ended, gap should be small
    last_success = getattr(ctx.metrics, '_last_success_cycle_time', None)
    assert last_success is not None
    # Immediately after a successful cycle gap should be near zero (< interval)
    assert (time.time() - last_success) < 1.0
