from __future__ import annotations

import os
import sys
import time
import json
import subprocess
from pathlib import Path


def _script_path() -> Path:
    direct = Path('c:/Users/Asus/Desktop/g6_reorganized/scripts/ml/ensemble_consensus_exporter.py')
    if direct.exists():
        return direct
    return Path(__file__).parents[2] / 'scripts' / 'ml' / 'ensemble_consensus_exporter.py'


def _write_bucket(fp: Path, ts: str, a: float, b: float) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        'timestamp,prediction,model,index,horizon',
        f'{ts},{a},sk_hgb_regressor,NIFTY,1',
        f'{ts},{b},xgb_regressor,NIFTY,1'
    ]
    fp.write_text('\n'.join(lines), encoding='utf-8')


def _append_bucket(fp: Path, ts: str, a: float, b: float) -> None:
    # Preserve header; append two prediction rows for new bucket time
    with fp.open('a', encoding='utf-8') as f:
        f.write(f'\n{ts},{a},sk_hgb_regressor,NIFTY,1')
        f.write(f'\n{ts},{b},xgb_regressor,NIFTY,1')


def test_forecast_inflation_from_predicted_disagreement(tmp_path, monkeypatch):
    """Run exporter across two iterations with changing disagreement.

    First bucket: high disagreement (std ~= 10). Second bucket: low disagreement (std ~= 1).
    EMA prediction before second iteration remains high (~10), triggering forecast inflation.
    Expect applied_k_source to end with '+forecast' and applied_k >= 9.
    """
    from src.web.dashboard.core import paths as real_paths
    monkeypatch.setattr(real_paths, 'project_root', lambda: tmp_path, raising=True)

    pred_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY.csv'
    # Bucket 1: large spread
    _write_bucket(pred_fp, '2025-11-10 09:15:00', 100, 120)

    # Calibration sidecar (band radius small so forecast drives inflation)
    calib_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_calibration.json'
    calib_fp.write_text(json.dumps({
        'timestamp': 1700000000000,
        'recommended_k': 1.0,
        'k_smooth': 1.0,
        'band_radius': 0.2,  # ensures band inflation not dominant (dis will be 10 then 1)
        'target': 0.8,
        'index': 'NIFTY',
        'horizon': '1',
        'n': 10
    }, indent=2), encoding='utf-8')

    env = os.environ.copy(); env['G6_PROJECT_ROOT'] = str(tmp_path)
    # Start exporter (no --once) rapid interval
    proc = subprocess.Popen([
        sys.executable, str(_script_path()), '--index', 'NIFTY', '--horizon', '1', '--interval', '1', '--inflate-k-from-forecast'
    ], cwd=str(tmp_path), env=env)

    try:
        # Allow first iteration to process
        time.sleep(2.0)
        # Append second bucket with low disagreement lines
        _append_bucket(pred_fp, '2025-11-10 09:16:00', 110, 111)
        # Wait for second iteration
        time.sleep(2.0)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    out_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble.csv'
    assert out_fp.exists(), 'ensemble output missing'
    lines = out_fp.read_text(encoding='utf-8').splitlines()
    header = lines[0].split(',')
    last = lines[-1].split(',')
    src_i = header.index('applied_k_source')
    k_i = header.index('applied_k')
    dis_i = header.index('disagreement')
    pred_i = header.index('predicted_disagreement')
    applied_k = float(last[k_i])
    dis = float(last[dis_i])
    pred = float(last[pred_i])
    # Validate forecast path triggered
    assert last[src_i].endswith('+forecast'), f'source did not reflect forecast inflation: {last[src_i]}'
    assert pred > dis, 'predicted disagreement not greater than current disagreement'
    # Applied k should inflate roughly to pred/dis (allow slack for float rounding)
    assert applied_k >= (pred / max(dis, 1e-6)) - 0.5, f'applied_k {applied_k} lower than expected ratio {pred/dis}'
