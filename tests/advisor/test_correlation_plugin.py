import time
from src.advisor.core import AdvisorContext, build_default_engine, Finding

def test_correlation_ann_path_triggers():
    ctx = AdvisorContext(indices=['NIFTY'], horizons=[60], windows=[60], now=time.time(), params={})
    eng = build_default_engine(ctx)
    # Seed findings into cache as if produced by prior plugins
    ctx.cache['findings'] = [
        Finding(code='ann_effectiveness_low', plugin='ANN', severity='crit', summary='x', confidence=0.9, index='NIFTY'),
        Finding(code='path_coverage_gap', plugin='PATH', severity='warn', summary='x', confidence=0.7, index='NIFTY'),
    ]
    report = eng.run(ctx)
    # Expect composite metric present
    metrics = report['metrics']
    assert any(m['name']=='advisor_composite_risk' and m['labels'].get('index')=='NIFTY' for m in metrics)