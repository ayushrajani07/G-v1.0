from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _script_path() -> Path:
    direct = Path('c:/Users/Asus/Desktop/g6_reorganized/scripts/ml/ensemble_consensus_exporter.py')
    if direct.exists():
        return direct
    return Path(__file__).parents[2] / 'scripts' / 'ml' / 'ensemble_consensus_exporter.py'


def _write_predictions(fp: Path) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    # Two models produce disagreement (std ~2)
    fp.write_text('\n'.join([
        'timestamp,prediction,model,index,horizon',
        '2025-11-10 09:15:00,100,sk_hgb_regressor,NIFTY,1',
        '2025-11-10 09:15:00,104,xgb_regressor,NIFTY,1'
    ]), encoding='utf-8')


def _read_last(out_fp: Path):
    txt = out_fp.read_text(encoding='utf-8')
    lines = txt.splitlines()
    header = lines[0].split(',')
    last = lines[-1].split(',')
    return header, last


def test_inflate_k_from_band_radius(tmp_path, monkeypatch):
    # Monkeypatch project root resolution
    from src.web.dashboard.core import paths as real_paths
    monkeypatch.setattr(real_paths, 'project_root', lambda: tmp_path, raising=True)

    pred_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY.csv'
    _write_predictions(pred_fp)

    # Calibration sidecar: recommended_k=1.0, k_smooth=1.0, band_radius forces k inflation (band_radius/dis = 2.5)
    side_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_calibration.json'
    side_fp.write_text(json.dumps({
        'timestamp': 1700000000000,
        'recommended_k': 1.0,
        'k_smooth': 1.0,
        'band_radius': 5.0,
        'target': 0.8,
        'index': 'NIFTY',
        'horizon': '1',
        'n': 25
    }, indent=2), encoding='utf-8')

    env = os.environ.copy(); env['G6_PROJECT_ROOT'] = str(tmp_path)
    subprocess.Popen([sys.executable, str(_script_path()), '--index', 'NIFTY', '--horizon', '1', '--interval', '1', '--inflate-k-from-forecast', '--once'], cwd=str(tmp_path), env=env).wait(timeout=10)

    out_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble.csv'
    header, last = _read_last(out_fp)
    src_i = header.index('applied_k_source')
    k_i = header.index('applied_k')
    dis_i = header.index('disagreement')
    k_val = float(last[k_i])
    dis = float(last[dis_i])
    # Expect inflation triggered and source annotated
    assert last[src_i].endswith('+forecast'), f"source={last[src_i]}"
    assert k_val >= 2.5 - 1e-6, f"expected k >= 2.5 from band radius/dis, got {k_val}"  # 5.0 / 2.0
    # Check scaled radius matches applied_k * disagreement within tolerance
    scaled_i = header.index('scaled_radius')
    scaled = float(last[scaled_i])
    assert abs(scaled - (dis * k_val)) < 1e-6
