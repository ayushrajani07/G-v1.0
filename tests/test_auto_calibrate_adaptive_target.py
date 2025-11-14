import json
import os
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta

import pytest

# We will import the script as a module to call main via a subprocess-like pattern.
# To avoid modifying sys.path globally, rely on project_root discovery identical to script behavior.

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_REL = REPO_ROOT / 'scripts' / 'ml' / 'auto_calibrate_ensemble.py'


def _write_ensemble_csv(tmp: Path, index: str, horizon: str, rows):
    # minimal required header + optional weighted_consensus
    header = 'timestamp,consensus,disagreement,index,horizon,weighted_consensus'  # include weighted to exercise branch
    lines = [header]
    for r in rows:
        # ensure timestamp is epoch ms string for simplicity
        lines.append(f"{r['timestamp']},{r['consensus']},{r['disagreement']},{index},{horizon},{r['consensus']}")
    (tmp / f"{index}_ensemble.csv").write_text('\n'.join(lines), encoding='utf-8')


def _write_live_tp(tmp_root: Path, index: str, expiry_tag: str, offset: str, rows):
    # path: data/g6_data/<INDEX>/<expiry_tag>/<offset>/<YYYY-MM-DD>.csv
    day_str = datetime.fromtimestamp(rows[0]['timestamp']/1000).strftime('%Y-%m-%d')
    p = tmp_root / 'data' / 'g6_data' / index / expiry_tag / offset / f'{day_str}.csv'
    p.parent.mkdir(parents=True, exist_ok=True)
    # minimal CSV: timestamp,tp
    content = 'timestamp,tp\n' + '\n'.join(f"{datetime.fromtimestamp(r['timestamp']/1000).strftime('%Y-%m-%d %H:%M:%S')},{r['tp']}" for r in rows)
    p.write_text(content, encoding='utf-8')


def _read_sidecar(tmp: Path, index: str):
    side = tmp / f"{index}_ensemble_k_calibration.json"
    if not side.exists():
        return {}
    return json.loads(side.read_text(encoding='utf-8'))


def _run_calibrator(tmp: Path, index: str, horizon: str, extra_args: list[str]):
    import subprocess, sys
    env = os.environ.copy()
    # Move working directory to script root expectation (project_root/data/ml/live_predictions)
    # We simulate project_root by setting CWD to repo root (tmp.parent if we created live_predictions under tmp?)
    # Simpler: invoke python with -c import run by adjusting sys.path via PYTHONPATH
    cmd = [sys.executable, str(SCRIPT_REL), '--index', index, '--horizon', horizon, '--interval', '0'] + extra_args
    subprocess.check_call(cmd, cwd=str(tmp.parent))


@pytest.mark.parametrize('direction', ['under', 'over'])
def test_adaptive_target_moves(direction, monkeypatch, tmp_path):
    index = 'NIFTY'
    horizon = '1'
    live_dir = tmp_path / 'data' / 'ml' / 'live_predictions'
    live_dir.mkdir(parents=True, exist_ok=True)

    # Generate synthetic ensemble + tp rows for ~65 minutes so both fast (15) and slow (60) windows have data
    now = int(time.time() * 1000)
    rows_ensemble = []
    rows_tp = []
    # We design disagreement constant and shape residuals so coverage is systematically low or high
    # If direction == 'under': residuals exceed band_radius & k*disagreement more often -> low coverage, target should raise
    # If direction == 'over': residuals within band frequently -> high coverage, target should lower
    base_pred = 100.0
    disagreement = 2.0
    for i in range(65):  # minutes
        ts = now - (65 - i) * 60_000
        # consensus prediction driftless
        pred = base_pred
        # tp actual deviates
        if direction == 'under':
            tp = base_pred + 5.0  # large residual => under-coverage
        else:
            tp = base_pred + 0.2  # small residual => over-coverage
        rows_ensemble.append({'timestamp': ts, 'consensus': pred, 'disagreement': disagreement})
        rows_tp.append({'timestamp': ts, 'tp': tp})

    _write_ensemble_csv(live_dir, index, horizon, rows_ensemble)
    _write_live_tp(tmp_path, index, 'this_week', '0', rows_tp)

    # Run calibrator with adaptive target enabled; step large enough to move in single iteration
    extra = [
        '--target', '0.80', '--window-minutes', '60', '--grid', '0.5,1.0,1.5', '--adaptive-target',
        '--target-min', '0.70', '--target-max', '0.90', '--target-step', '0.05',
        '--fast-window-minutes', '15', '--slow-window-minutes', '60'
    ]

    # Monkeypatch project_root() to point to tmp_path parent (so script finds our data folder)
    from src.web.dashboard.core import paths as _paths
    monkeypatch.setattr(_paths, 'project_root', lambda: tmp_path)

    import subprocess, sys
    cmd = [sys.executable, str(SCRIPT_REL), '--index', index, '--horizon', horizon, '--interval', '0'] + extra
    subprocess.check_call(cmd, cwd=str(tmp_path))

    side = _read_sidecar(live_dir, index)
    assert side, 'Sidecar should exist'
    assert 'dynamic_target_coverage' in side and 'adaptive_state' in side
    dyn = side['dynamic_target_coverage']
    state = side['adaptive_state']
    if direction == 'under':
        assert state in ('raising','stable'), f"expected raising or stable state, got {state}"  # stable when already at max
        assert dyn >= 0.80, f"Expected target to raise (>=0.80), got {dyn}"
    else:
        assert state in ('lowering','stable'), f"expected lowering or stable state, got {state}"
        assert dyn <= 0.80, f"Expected target to lower (<=0.80), got {dyn}"


def test_adaptive_state_insufficient_data(monkeypatch, tmp_path):
    index = 'NIFTY'
    horizon = '1'
    live_dir = tmp_path / 'data' / 'ml' / 'live_predictions'
    live_dir.mkdir(parents=True, exist_ok=True)

    # Only a few minutes of data -> fast window maybe ok, slow window insufficient
    now = int(time.time() * 1000)
    rows_ensemble = []
    rows_tp = []
    for i in range(5):
        ts = now - (5 - i) * 60_000
        rows_ensemble.append({'timestamp': ts, 'consensus': 100.0, 'disagreement': 2.0})
        rows_tp.append({'timestamp': ts, 'tp': 100.1})
    _write_ensemble_csv(live_dir, index, horizon, rows_ensemble)
    _write_live_tp(tmp_path, index, 'this_week', '0', rows_tp)

    extra = [
        '--target', '0.80', '--window-minutes', '60', '--grid', '0.5,1.0,1.5', '--adaptive-target',
        '--fast-window-minutes', '15', '--slow-window-minutes', '60'
    ]
    from src.web.dashboard.core import paths as _paths
    monkeypatch.setattr(_paths, 'project_root', lambda: tmp_path)
    import subprocess, sys
    cmd = [sys.executable, str(SCRIPT_REL), '--index', index, '--horizon', horizon, '--interval', '0'] + extra
    subprocess.check_call(cmd, cwd=str(tmp_path))

    side = _read_sidecar(live_dir, index)
    assert side
    assert side.get('adaptive_state') == 'insufficient'
    assert 'coverage_fast' in side and 'coverage_slow' in side
    # coverage_slow.n should reflect fewer points
    assert side['coverage_fast']['n'] >= side['coverage_slow']['n']
