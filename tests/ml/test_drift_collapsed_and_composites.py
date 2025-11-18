import csv
import math
from pathlib import Path
from datetime import datetime

from src.ml.drift_monitor import DriftMonitor
from src.ml import feature_loader as fl


def _write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _today_csv(index: str) -> Path:
    base = Path('data') / 'g6_data' / index.upper() / 'this_month' / '0'
    today = datetime.now().strftime('%Y-%m-%d')
    return base / f'{today}.csv'


def test_collapsed_bins_constant_values(tmp_path):
    p = _today_csv('NIFTY')
    rows = [{'tp': 100.0} for _ in range(20)]
    _write_csv(p, rows, ['tp'])

    m = DriftMonitor(baseline_days=1, recent_rows=100)
    b = m.compute_feature_distributions('NIFTY', 0, features=['tp'])
    r = m.compute_feature_distributions('NIFTY', 0, features=['tp'])
    d = m.calculate_drift_metrics(b, r)['tp']

    assert math.isfinite(d['psi']) and abs(d['psi']) < 1e-9
    assert math.isfinite(d['mean_delta']) and abs(d['mean_delta']) < 1e-9
    assert math.isfinite(d['mean_delta_zscore'])
    assert math.isfinite(d['var_ratio'])
    assert d['severity'] in {'stable','watch','actionable','critical'}


def test_composite_transforms_ratio_diff(tmp_path, monkeypatch):
    p = _today_csv('BANKNIFTY')
    rows = [
        {'tp': 100.0, 'ce_iv': 0.2},
        {'tp': 110.0, 'ce_iv': 0.25},
        {'tp': 120.0, 'ce_iv': 0.3},
    ]
    _write_csv(p, rows, ['tp','ce_iv'])

    mapping = {
        'tp_over_iv': fl.FeatureSpec('tp_over_iv', csv_col='tp', importance=10, transform='ratio', src1='tp', src2='ce_iv'),
        'tp_minus_iv': fl.FeatureSpec('tp_minus_iv', csv_col='tp', importance=11, transform='diff', src1='tp', src2='ce_iv'),
    }
    monkeypatch.setattr(fl, 'load_feature_map', lambda: mapping)

    m = DriftMonitor(baseline_days=1, recent_rows=100)
    dist = m.compute_feature_distributions('BANKNIFTY', 0, features=['tp_over_iv','tp_minus_iv'])
    feats = dist['features']
    assert 'tp_over_iv' in feats and 'tp_minus_iv' in feats
    vals_ratio = feats['tp_over_iv']['values']
    vals_diff = feats['tp_minus_iv']['values']
    # Validate first row computations
    assert abs(vals_ratio[0] - (100.0 / 0.2)) < 1e-9
    assert abs(vals_diff[0] - (100.0 - 0.2)) < 1e-9
