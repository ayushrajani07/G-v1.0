import csv
import math
from pathlib import Path
from datetime import datetime

from src.ml.drift_monitor import DriftMonitor


def _write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _today_csv_path(index: str) -> Path:
    base = Path('data') / 'g6_data' / index.upper() / 'this_month' / '0'
    today = datetime.now().strftime('%Y-%m-%d')
    return base / f'{today}.csv'


def test_identical_distributions_yield_near_zero_psi(tmp_path, monkeypatch):
    # Prepare identical data for baseline and recent windows
    p = _today_csv_path('NIFTY')
    rows = [
        {'tp': v, 'ce_iv': 0.2} for v in [100.0, 101.0, 102.0, 103.0, 104.0]
    ]
    _write_csv(p, rows, fieldnames=['tp', 'ce_iv'])

    m = DriftMonitor(baseline_days=1, recent_rows=100)
    baseline = m.compute_feature_distributions('NIFTY', lookback_days=0, features=['tp'])
    recent = m.compute_feature_distributions('NIFTY', lookback_days=0, features=['tp'])

    drift = m.calculate_drift_metrics(baseline, recent)
    assert 'tp' in drift
    d = drift['tp']
    assert abs(d['psi']) < 1e-6
    assert abs(d['mean_delta']) < 1e-9
    assert math.isfinite(d['var_ratio']) and abs(d['var_ratio'] - 1.0) < 1e-9
    assert d['severity'] == 'stable'


def test_small_sample_no_nan(tmp_path, monkeypatch):
    # Very small sample sizes should not produce NaN or crash
    p = _today_csv_path('BANKNIFTY')
    rows_recent = [{'tp': v} for v in [10.0, 10.1]]  # 2 points
    _write_csv(p, rows_recent, fieldnames=['tp'])

    m = DriftMonitor(baseline_days=1, recent_rows=2)
    # Use the same tiny window for baseline and recent (quantiles computed internally)
    baseline = m.compute_feature_distributions('BANKNIFTY', lookback_days=0, features=['tp'])
    recent = m.compute_feature_distributions('BANKNIFTY', lookback_days=0, features=['tp'])

    drift = m.calculate_drift_metrics(baseline, recent)
    d = drift['tp']
    for k in ['psi', 'mean_delta', 'mean_delta_zscore', 'var_ratio']:
        assert math.isfinite(float(d[k]))
    assert d['severity'] in {'stable', 'watch', 'actionable', 'critical'}
