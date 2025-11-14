import os, time, threading, requests
from pathlib import Path
import subprocess, sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / 'scripts' / 'ml' / 'ann_health_exporter.py'
BASELINE = REPO_ROOT / 'baselines' / 'ann_daily_baseline.json'

PORT = 9321  # ephemeral test port

# Simple HTTP fetch helper

def fetch_metrics(port: int) -> str:
    url = f'http://127.0.0.1:{port}'
    # prometheus_client start_http_server listens at root '/'
    for _ in range(40):  # retry ~8s
        try:
            r = requests.get(url, timeout=0.5)
            if r.status_code == 200 and 'ann_health_speedup' in r.text:
                return r.text
        except Exception:
            pass
        time.sleep(0.2)
    raise AssertionError('metrics not available or missing expected gauge')

def test_exporter_once_smoke():
    assert SCRIPT.exists(), 'Exporter script missing'
    assert BASELINE.exists(), 'Baseline file missing'
    env = os.environ.copy()
    env['PYTHONPATH'] = str(REPO_ROOT)
    cmd = [sys.executable, str(SCRIPT), '--index','NIFTY','--tag','this_week','--offset','0','--days-back','3','--baseline', str(BASELINE), '--port', str(PORT), '--interval','2','--min-rows','1','--verbose','--once']
    proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # Wait for process exit (single run); concurrently fetch metrics before it exits.
    metrics_text = fetch_metrics(PORT)
    out, _ = proc.communicate(timeout=60)
    assert proc.returncode == 0, f'Exporter failed: {out}'
    # Basic assertions: presence of new gauges
    assert 'ann_health_effectiveness_adjusted' in metrics_text, 'Adjusted effectiveness gauge missing'
    assert 'ann_health_guard_trigger_rate' in metrics_text, 'Guard trigger rate gauge missing'
    assert 'ann_health_regression_total' in metrics_text, 'Regression total gauge missing'
    assert 'ann_health_last_run_timestamp_seconds' in metrics_text, 'Timestamp gauge missing'
