import csv
from pathlib import Path
from datetime import datetime

from src.ml.drift_monitor import DriftMonitor
from src.ml import feature_loader as fl


def _write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['tp','ce_iv','noise'])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_feature_mapping_and_transform(tmp_path, monkeypatch):
    base = Path('data') / 'g6_data' / 'NIFTY' / 'this_month' / '0'
    today = datetime.now().strftime('%Y-%m-%d')
    p = base / f'{today}.csv'
    # tp: 99..101; ce_iv: 0.2..0.22; noise present but not mapped
    _write_csv(p, [
        {'tp': 100.0+i, 'ce_iv': 0.2 + i*0.01, 'noise': 999} for i in range(3)
    ])
    # Override feature map to include a transformed feature variant
    mapping = {
        'tp': fl.FeatureSpec('tp','tp',10,'identity'),
        'ce_iv': fl.FeatureSpec('ce_iv','ce_iv',20,'identity'),
        'tp_log': fl.FeatureSpec('tp_log','tp',30,'log1p'),
    }
    monkeypatch.setenv('G6_DRIFT_FEATURE_MAP_JSON','')  # ensure default path ignored
    # Monkeypatch loader to return our mapping
    monkeypatch.setattr(fl, 'load_feature_map', lambda: mapping)
    m = DriftMonitor(baseline_days=1, recent_rows=100)
    # Compute distributions for explicit features list (uses mapping for transforms)
    dist = m.compute_feature_distributions('NIFTY', lookback_days=0, features=['tp','ce_iv','tp_log'])
    feats = dist['features']
    assert 'tp' in feats and 'ce_iv' in feats and 'tp_log' in feats
    # Check values count matches 3 rows
    assert len(feats['tp']['values']) == 3
    assert len(feats['tp_log']['values']) == 3
    # tp_log should be log1p(tp) for the first row
    import math
    assert abs(feats['tp_log']['values'][0] - math.log1p(100.0)) < 1e-9
