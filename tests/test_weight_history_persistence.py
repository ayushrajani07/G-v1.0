import os, tempfile, json
from src.ml.weight_history import record_weights, get_weight_volatility, flush_history, load_history, get_store


def test_weight_history_persistence_roundtrip():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, 'weight_history.json')
    os.environ['ML_WEIGHT_HISTORY_FILE'] = path
    # Record several samples
    for i in range(5):
        record_weights('NIFTY', 60, {'gbrt': 0.6 + i*0.01, 'retrieval': 0.4 - i*0.005})
    # Flush explicitly
    flush_history()
    assert os.path.exists(path)
    size_before = os.path.getsize(path)
    # Reset in-memory store (simulate restart)
    from src.ml import weight_history as wh
    wh._store = None  # type: ignore
    # Load history
    load_history()
    vol_g, vol_r = get_weight_volatility('NIFTY', 60)
    # Volatility should be non-zero due to variation
    assert vol_g > 0.0 or vol_r > 0.0
    # Ensure file isn't empty
    assert size_before > 10
