import time
from src.advisor.core import AdvisorContext, build_default_engine

def test_universal_advisor_smoke():
    ctx = AdvisorContext(indices=['NIFTY'], horizons=[60], windows=[60], now=time.time(), params={})
    eng = build_default_engine(ctx)
    report = eng.run(ctx)
    assert 'summary' in report
    assert 'flags' in report
    assert isinstance(report['summary'].get('health_score'), int)
