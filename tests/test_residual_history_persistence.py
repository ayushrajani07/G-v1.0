import os, tempfile
from src.ml.residuals import record_residual, get_residual_stats, flush_residual_history, load_residual_history, _store as _res_store


def test_residual_history_persistence_roundtrip():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, 'residual_history.json')
    os.environ['ML_RESIDUAL_HISTORY_FILE'] = path
    # Record residuals
    for i in range(40):
        record_residual('NIFTY', 60, 1.0 + 0.01*i)
    flush_residual_history()
    assert os.path.exists(path)
    size_before = os.path.getsize(path)
    # Reset store to simulate restart
    import src.ml.residuals as rmod
    rmod._store = None  # type: ignore
    load_residual_history()
    stats = get_residual_stats('NIFTY', [60])[0]
    assert stats.count > 0
    assert stats.avg > 0
    assert stats.p95 >= stats.avg * 0.9  # loose sanity
    assert size_before > 50
