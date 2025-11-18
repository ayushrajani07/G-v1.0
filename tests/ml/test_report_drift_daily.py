import json, os, time, subprocess, sys
from pathlib import Path

from src.web.dashboard import drift_metrics
from src.web.dashboard.drift_metrics import start_drift_evaluator, stop_drift_evaluator


def test_daily_report_generation(monkeypatch):
    monkeypatch.setenv('G6_DRIFT_ENABLE','1')
    monkeypatch.setenv('G6_DRIFT_INDICES','NIFTY')
    start_drift_evaluator()
    time.sleep(3.5)
    out_path = Path('reports') / 'drift' / 'daily_test.json'
    cmd = [sys.executable, 'scripts/ml/report_drift_daily.py', '--indices', 'NIFTY', '--output', str(out_path)]
    subprocess.check_call(cmd)
    assert out_path.exists(), 'Daily drift report not created'
    data = json.loads(out_path.read_text(encoding='utf-8'))
    assert 'aggregate_counts' in data and 'per_index' in data
    assert data['per_index'][0]['index'] == 'NIFTY'
    stop_drift_evaluator()
