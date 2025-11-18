import os, csv
from pathlib import Path
from datetime import datetime, timedelta

from src.ml.drift_monitor import DriftMonitor


def _write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['tp','ce_iv'])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_multiday_baseline_aggregation(tmp_path, monkeypatch):
    # Point project root discovery to current working directory (repo root assumed); files are relative
    # Create two days of data under data/g6_data/NIFTY/this_month/0/
    base = Path('data') / 'g6_data' / 'NIFTY' / 'this_month' / '0'
    today = datetime.now().date()
    d1 = today - timedelta(days=1)
    d2 = today - timedelta(days=0)
    p1 = base / f'{d1:%Y-%m-%d}.csv'
    p2 = base / f'{d2:%Y-%m-%d}.csv'
    _write_csv(p1, [{'tp': 100.0, 'ce_iv': 0.2} for _ in range(5)])
    _write_csv(p2, [{'tp': 110.0, 'ce_iv': 0.25} for _ in range(7)])

    m = DriftMonitor(baseline_days=2, recent_rows=10)
    baseline = m.compute_feature_distributions('NIFTY', lookback_days=2, features=['tp'])
    feats = baseline['features']
    assert 'tp' in feats
    # Expect 12 values aggregated
    assert len(feats['tp']['values']) == 12

    # Recent should only use latest day
    recent = m.compute_feature_distributions('NIFTY', lookback_days=0, features=['tp'])
    assert len(recent['features']['tp']['values']) == 7
