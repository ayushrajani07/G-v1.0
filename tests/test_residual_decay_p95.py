import time, os
from src.ml.residuals import record_residual, get_residual_stats


def test_decay_weighted_p95_present_and_reasonable():
    os.environ['ML_RESIDUAL_MAX_AGE_SECONDS'] = '3600'
    os.environ['ML_RESIDUAL_DECAY_HALF_LIFE_SECONDS'] = '1'  # strong decay
    idx = 'NIFTY'
    hz = 60
    now = time.time()
    # Older large residual should decay
    record_residual(idx, hz, 10.0, ts=now - 10)
    # Recent moderate residuals
    for r in [2.0, 3.0, 4.0, 5.0]:
        record_residual(idx, hz, r, ts=now - 0.1)
    stats = get_residual_stats(idx, [hz])[0]
    assert stats.p95_decay <= stats.p95  # heavy decay on old large value likely lowers weighted tail
    assert stats.p95_decay >= min(stats.avg, 0.0)
    assert stats.p95_decay > 0
