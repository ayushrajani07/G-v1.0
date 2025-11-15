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


def test_override_auto_revert_after_stability(tmp_path, monkeypatch):
    # Monkeypatch project root resolution for exporter (web_paths.project_root())
    from src.web.dashboard.core import paths as real_paths
    monkeypatch.setattr(real_paths, 'project_root', lambda: tmp_path, raising=True)

    pred_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY.csv'
    _write_predictions(pred_fp)

    # Calibration sidecar with coverage metrics within tolerance of target
    # exporter uses coverage_fast/coverage_slow value fields to judge stability
    side_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_calibration.json'
    side_fp.write_text(json.dumps({
        'timestamp': 1700000000000,
        'recommended_k': 1.30,
        'k_smooth': 1.10,
        'effective_cov': 0.81,
        'band_radius': 12.3,
        'target': 0.80,
        'index': 'NIFTY',
        'horizon': '1',
        'n': 50,
        'coverage_fast': {'value': 0.805},
        'coverage_slow': {'value': 0.798}
    }, indent=2), encoding='utf-8')

    # Override file with manual k (no expiry)
    ov_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_overrides.json'
    ov_fp.write_text(json.dumps({'overrides': {'1': {'k': 1.6, 'expires': None}}}, indent=2), encoding='utf-8')

    script = _script_path()
    env = os.environ.copy(); env['G6_PROJECT_ROOT'] = str(tmp_path)
    exe = sys.executable

    # Run exporter three times with auto-revert enabled to allow removal on second run and observation on third
    for i in range(3):
        subprocess.Popen([
            exe, str(script), '--index', 'NIFTY', '--horizon', '1', '--interval', '1', '--once',
            '--override-auto-revert', '--override-target-tolerance', '0.01', '--override-sustain-cycles', '2'
        ], cwd=str(tmp_path), env=env).wait(timeout=15)
        # After each run inspect overrides file
        data = json.loads(ov_fp.read_text(encoding='utf-8')) if ov_fp.exists() else {}
        ovs = data.get('overrides') if isinstance(data, dict) else None
        if i == 0:
            # First run: override present, stable_cycles should be 1
            assert isinstance(ovs, dict) and '1' in ovs, 'override missing after first run'
            assert int((ovs['1'].get('stable_cycles') or 0)) == 1
        elif i == 1:
            # Second run: override removed (auto-revert triggered) but applied_k_source for this run still 'override'
            # removal occurs post source assignment; file should have no horizon entry
            assert isinstance(ovs, dict) and '1' not in ovs, 'override not auto-removed after second run'
        else:
            # Third run: no override; ensemble output should reflect smooth source
            out_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble.csv'
            header, last = _read_last(out_fp)
            src_i = header.index('applied_k_source')
            k_i = header.index('applied_k')
            assert last[src_i] == 'smooth'
            # k should match k_smooth (1.10)
            assert abs(float(last[k_i]) - 1.10) < 1e-6
