from __future__ import annotations

from pathlib import Path
import os
import json
import subprocess, sys

import importlib

mod = importlib.import_module('scripts.ml.ensemble_consensus_exporter')


def write_predictions(fp: Path, horizon: str = "1"):
    fp.parent.mkdir(parents=True, exist_ok=True)
    # Minimal predictions with two models at the same bucket so disagreement > 0
    lines = [
        "timestamp,prediction,model,index,horizon",
        "2025-11-10 09:15:00,100,sk_hgb_regressor,NIFTY,{}".format(horizon),
        "2025-11-10 09:15:00,104,xgb_regressor,NIFTY,{}".format(horizon),
    ]
    fp.write_text("\n".join(lines), encoding="utf-8")


def test_applied_k_prefers_smooth_when_available(tmp_path, monkeypatch):
    # Route project_root to tmp
    from src.web.dashboard.core import paths as real_paths
    monkeypatch.setattr(real_paths, 'project_root', lambda: tmp_path, raising=True)

    # Input predictions
    in_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY.csv'
    write_predictions(in_fp, horizon="1")

    # Calibration sidecar with both values
    side_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_calibration.json'
    side_fp.write_text(json.dumps({
        'timestamp': 1700000000000,
        'recommended_k': 1.25,
        'k_smooth': 1.10,
        'effective_cov': 0.81,
        'band_radius': 12.3,
        'target': 0.8,
        'index': 'NIFTY',
        'horizon': '1',
        'n': 50
    }, indent=2), encoding='utf-8')

    # Run exporter once (should pick k_smooth by default)
    script = Path('c:/Users/Asus/Desktop/g6_reorganized/scripts/ml/ensemble_consensus_exporter.py')
    if not script.exists():
        script = Path(__file__).parents[2] / 'scripts' / 'ml' / 'ensemble_consensus_exporter.py'
    exe = sys.executable
    env = os.environ.copy()
    env.pop('G6_USE_RAW_K', None)
    subprocess.Popen([exe, str(script), '--index', 'NIFTY', '--horizon', '1', '--interval', '1', '--once'], cwd=str(tmp_path), env=env).wait(timeout=10)

    out_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble.csv'
    text = out_fp.read_text(encoding='utf-8')
    lines = text.splitlines()
    header = lines[0].split(',')
    src_i = header.index('applied_k_source')
    k_i = header.index('applied_k')
    dis_i = header.index('disagreement')
    scaled_i = header.index('scaled_radius')
    last = lines[-1].split(',')
    assert last[src_i] == 'smooth'
    k_val = float(last[k_i])
    assert abs(k_val - 1.10) < 1e-6
    dis = float(last[dis_i])
    scaled = float(last[scaled_i])
    assert abs(scaled - (dis * k_val)) < 1e-6


def test_override_wins_over_smooth(tmp_path, monkeypatch):
    from src.web.dashboard.core import paths as real_paths
    monkeypatch.setattr(real_paths, 'project_root', lambda: tmp_path, raising=True)

    # Input predictions
    in_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY.csv'
    write_predictions(in_fp, horizon="1")

    # Calibration sidecar and override file
    side_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_calibration.json'
    side_fp.write_text(json.dumps({
        'timestamp': 1700000000000,
        'recommended_k': 1.25,
        'k_smooth': 1.10,
        'effective_cov': 0.81,
        'band_radius': 12.3,
        'target': 0.8,
        'index': 'NIFTY',
        'horizon': '1',
        'n': 50
    }, indent=2), encoding='utf-8')

    ov_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_overrides.json'
    # override k=1.5 without expiry
    ov_fp.write_text(json.dumps({'overrides': {'1': {'k': 1.5, 'expires': None}}}, indent=2), encoding='utf-8')

    script = Path('c:/Users/Asus/Desktop/g6_reorganized/scripts/ml/ensemble_consensus_exporter.py')
    if not script.exists():
        script = Path(__file__).parents[2] / 'scripts' / 'ml' / 'ensemble_consensus_exporter.py'
    exe = sys.executable
    env = os.environ.copy()
    subprocess.Popen([exe, str(script), '--index', 'NIFTY', '--horizon', '1', '--interval', '1', '--once'], cwd=str(tmp_path), env=env).wait(timeout=10)

    out_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble.csv'
    text = out_fp.read_text(encoding='utf-8')
    lines = text.splitlines()
    header = lines[0].split(',')
    src_i = header.index('applied_k_source')
    k_i = header.index('applied_k')
    last = lines[-1].split(',')
    assert last[src_i] == 'override'
    k_val = float(last[k_i])
    assert abs(k_val - 1.5) < 1e-6
