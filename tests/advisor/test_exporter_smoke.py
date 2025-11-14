import time
from src.advisor.core import AdvisorContext, build_default_engine

def test_exporter_cycle_simulation():
    """Simulate one exporter cycle (no HTTP) and verify expected keys.

    Ensures engine run used by exporter provides health_score & overall_level.
    """
    ctx = AdvisorContext(indices=['NIFTY','BANKNIFTY'], horizons=[60], windows=[60,120], now=time.time(), params={})
    eng = build_default_engine(ctx)
    report = eng.run(ctx)
    summary = report['summary']
    assert 'health_score' in summary
    assert 'overall_level' in summary
    assert isinstance(summary['health_score'], int)
    assert summary['overall_level'] in ('ok','warn','crit','unknown')