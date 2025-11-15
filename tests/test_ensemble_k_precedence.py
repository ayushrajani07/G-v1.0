from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _script_path() -> Path:
    # Resolve exporter script path (direct or relative)
    direct = Path('c:/Users/Asus/Desktop/g6_reorganized/scripts/ml/ensemble_consensus_exporter.py')
    if direct.exists():
        return direct
    return Path(__file__).parents[2] / 'scripts' / 'ml' / 'ensemble_consensus_exporter.py'


def _write_predictions(fp: Path, horizon: str = '1') -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text('\n'.join([
        'timestamp,prediction,model,index,horizon',
        f'2025-11-10 09:15:00,100,sk_hgb_regressor,NIFTY,{horizon}',
        f'2025-11-10 09:15:00,104,xgb_regressor,NIFTY,{horizon}',
    ]), encoding='utf-8')


def _read_last_row(out_fp: Path):
    text = out_fp.read_text(encoding='utf-8')
    lines = text.splitlines()
    header = lines[0].split(',')
    last = lines[-1].split(',')
    return header, last


def test_cli_flag_use_raw_k(tmp_path, monkeypatch):
    # project_root monkeypatch
    from src.web.dashboard.core import paths as real_paths
    monkeypatch.setattr(real_paths, 'project_root', lambda: tmp_path, raising=True)

    pred_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY.csv'
    _write_predictions(pred_fp)

    calib_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_calibration.json'
    calib_fp.write_text(json.dumps({
        'timestamp': 1700000000000,
        'recommended_k': 1.30,
        'k_smooth': 1.05,
        'band_radius': 10.0,
        'target': 0.8,
        'index': 'NIFTY',
        'horizon': '1',
        'n': 40
    }, indent=2), encoding='utf-8')

    env = os.environ.copy()
    env.pop('G6_USE_RAW_K', None)  # rely on CLI flag only
    env['G6_PROJECT_ROOT'] = str(tmp_path)
    subprocess.Popen([sys.executable, str(_script_path()), '--index', 'NIFTY', '--horizon', '1', '--interval', '1', '--use-raw-k', '--once'], cwd=str(tmp_path), env=env).wait(timeout=10)

    out_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble.csv'
    header, last = _read_last_row(out_fp)
    src_i = header.index('applied_k_source')
    k_i = header.index('applied_k')
    assert last[src_i] == 'raw'
    assert abs(float(last[k_i]) - 1.30) < 1e-6


def test_env_raw_k_with_override_still_override(tmp_path, monkeypatch):
    from src.web.dashboard.core import paths as real_paths
    monkeypatch.setattr(real_paths, 'project_root', lambda: tmp_path, raising=True)

    pred_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY.csv'
    _write_predictions(pred_fp)
    calib_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_calibration.json'
    calib_fp.write_text(json.dumps({
        'timestamp': 1700000000000,
        'recommended_k': 1.22,
        'k_smooth': 1.08,
        'band_radius': 9.5,
        'target': 0.8,
        'index': 'NIFTY',
        'horizon': '1',
        'n': 30
    }, indent=2), encoding='utf-8')
    ov_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_overrides.json'
    ov_fp.write_text(json.dumps({'overrides': {'1': {'k': 1.6, 'expires': None}}}, indent=2), encoding='utf-8')

    env = os.environ.copy()
    env['G6_USE_RAW_K'] = '1'
    env['G6_PROJECT_ROOT'] = str(tmp_path)
    subprocess.Popen([sys.executable, str(_script_path()), '--index', 'NIFTY', '--horizon', '1', '--interval', '1', '--once'], cwd=str(tmp_path), env=env).wait(timeout=10)
    out_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble.csv'
    header, last = _read_last_row(out_fp)
    src_i = header.index('applied_k_source')
    k_i = header.index('applied_k')
    assert last[src_i] == 'override'
    assert abs(float(last[k_i]) - 1.6) < 1e-6


def test_missing_k_smooth_falls_back_to_raw(tmp_path, monkeypatch):
    from src.web.dashboard.core import paths as real_paths
    monkeypatch.setattr(real_paths, 'project_root', lambda: tmp_path, raising=True)
    pred_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY.csv'
    _write_predictions(pred_fp)
    calib_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_calibration.json'
    # omit k_smooth
    calib_fp.write_text(json.dumps({
        'timestamp': 1700000000000,
        'recommended_k': 1.40,
        'band_radius': 11.0,
        'target': 0.8,
        'index': 'NIFTY',
        'horizon': '1',
        'n': 25
    }, indent=2), encoding='utf-8')
    env = os.environ.copy(); env.pop('G6_USE_RAW_K', None)
    env['G6_PROJECT_ROOT'] = str(tmp_path)
    subprocess.Popen([sys.executable, str(_script_path()), '--index', 'NIFTY', '--horizon', '1', '--interval', '1', '--once'], cwd=str(tmp_path), env=env).wait(timeout=10)
    out_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble.csv'
    header, last = _read_last_row(out_fp)
    src_i = header.index('applied_k_source')
    k_i = header.index('applied_k')
    assert last[src_i] == 'raw'
    assert abs(float(last[k_i]) - 1.40) < 1e-6


def test_expired_override_reverts_to_smooth(tmp_path, monkeypatch):
    from src.web.dashboard.core import paths as real_paths
    monkeypatch.setattr(real_paths, 'project_root', lambda: tmp_path, raising=True)
    pred_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY.csv'
    _write_predictions(pred_fp)
    calib_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_calibration.json'
    calib_fp.write_text(json.dumps({
        'timestamp': 1700000000000,
        'recommended_k': 1.10,
        'k_smooth': 1.05,
        'band_radius': 8.0,
        'target': 0.8,
        'index': 'NIFTY',
        'horizon': '1',
        'n': 20
    }, indent=2), encoding='utf-8')
    ov_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_overrides.json'
    # expired override (expires far in past)
    ov_fp.write_text(json.dumps({'overrides': {'1': {'k': 1.8, 'expires': 0}}}, indent=2), encoding='utf-8')
    env = os.environ.copy(); env.pop('G6_USE_RAW_K', None)
    env['G6_PROJECT_ROOT'] = str(tmp_path)
    subprocess.Popen([sys.executable, str(_script_path()), '--index', 'NIFTY', '--horizon', '1', '--interval', '1', '--once'], cwd=str(tmp_path), env=env).wait(timeout=10)
    out_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble.csv'
    header, last = _read_last_row(out_fp)
    src_i = header.index('applied_k_source')
    k_i = header.index('applied_k')
    # Expect smooth (override pruned)
    assert last[src_i] == 'smooth'
    assert abs(float(last[k_i]) - 1.05) < 1e-6
