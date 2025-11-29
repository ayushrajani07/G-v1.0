import time, os
from src.ml.residuals import record_residual, get_residual_stats


def test_residual_time_decay_prunes_old():
    os.environ['ML_RESIDUAL_MAX_AGE_SECONDS'] = '2'  # keep only last 2s
    os.environ['ML_RESIDUAL_DECAY_HALF_LIFE_SECONDS'] = '1'
    idx = 'NIFTY'
    hz = 60
    # Record three residuals spaced 1s apart
    t0 = time.time()
    record_residual(idx, hz, 1.0, ts=t0 - 5)  # very old, should be pruned
    record_residual(idx, hz, 2.0, ts=t0 - 1.5)  # borderline maybe pruned
    record_residual(idx, hz, 3.0, ts=t0)  # fresh
    stats = get_residual_stats(idx, [hz])[0]
    # Only fresh (and maybe borderline if within age) count
    assert stats.count <= 2
    assert stats.avg >= 0.0
    # Trend ratio should be defined
    assert stats.trend_ratio > 0
