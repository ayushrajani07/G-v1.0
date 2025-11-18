import json
from pathlib import Path

from src.ml.drift_monitor import DriftMonitor


def test_baseline_history_written(tmp_path):
    m = DriftMonitor(baseline_days=1, recent_rows=1)
    idx = 'NIFTY'
    baseline = {
        'index': idx,
        'lookback_days': 1,
        'features': {'tp': {'values': [1.0], 'mean': 1.0, 'std': 1.0, 'min': 1.0, 'max': 1.0, 'quantiles': [0,1]}},
    }
    ok = m.save_baseline(idx, baseline)
    assert ok
    hist_dir = m.baseline_history_dir / idx
    assert hist_dir.exists()
    entries = list(hist_dir.glob('baseline_*.json'))
    assert entries, 'No baseline history file created'
    # Save again, ensure version increments and another history file is created
    ok2 = m.save_baseline(idx, baseline)
    assert ok2
    entries2 = list(hist_dir.glob('baseline_*.json'))
    assert len(entries2) >= len(entries), 'Second history write missing'
