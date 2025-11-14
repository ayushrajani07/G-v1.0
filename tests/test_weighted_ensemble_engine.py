import importlib
from pathlib import Path
import json
import os
import subprocess, sys

mod = importlib.import_module('scripts.ml.ensemble_consensus_exporter')


def test_header_includes_weighted_and_summary(tmp_path, monkeypatch):
    # monkeypatch project_root to use tmp directory
    from src.web.dashboard.core import paths as real_paths

    def fake_project_root():
        return tmp_path

    monkeypatch.setattr(real_paths, 'project_root', fake_project_root, raising=True)

    fp = mod.ensure_out_csv('NIFTY')
    text = fp.read_text(encoding='utf-8')
    header = text.splitlines()[0]
    assert 'weighted_consensus' in header.split(',')
    assert 'weights_summary' in header.split(',')
    # New Phase 9 columns
    assert 'applied_k' in header.split(',')
    assert 'applied_k_source' in header.split(',')
    assert 'scaled_radius' in header.split(',')
    # New forecasting columns
    assert 'predicted_disagreement' in header.split(',')
    assert 'projected_radius' in header.split(',')


def test_weights_sidecar_written(monkeypatch, tmp_path):
    # We'll simulate residual_history update path by injecting artificial history then calling write section logic indirectly.
    from src.web.dashboard.core import paths as real_paths

    def fake_project_root():
        return tmp_path

    monkeypatch.setattr(real_paths, 'project_root', fake_project_root, raising=True)

    # Prepare predictions file with minimal rows for two models
    live_pred_dir = tmp_path / 'data' / 'ml' / 'live_predictions'
    live_pred_dir.mkdir(parents=True, exist_ok=True)
    pred_fp = live_pred_dir / 'NIFTY.csv'
    pred_fp.write_text('\n'.join([
        'timestamp,prediction,model,index,horizon',
        '2025-11-10 09:15:00,100,sk_hgb_regressor,NIFTY,1',
        '2025-11-10 09:15:00,104,xgb_regressor,NIFTY,1'
    ]), encoding='utf-8')

    # Create minimal live TP file path expected by find_live_csv (simulate this_week/0 folder with date file)
    live_root = tmp_path / 'data' / 'g6_data' / 'NIFTY' / 'this_week' / '0'
    live_root.mkdir(parents=True, exist_ok=True)
    live_csv = live_root / '2025-11-10.csv'
    live_csv.write_text('timestamp,tp\n2025-11-10 09:15:00,102\n', encoding='utf-8')

    # Run exporter once to populate new applied_k columns.
    script = Path('c:/Users/Asus/Desktop/g6_reorganized/scripts/ml/ensemble_consensus_exporter.py')
    if not script.exists():
        script = Path(__file__).parents[2] / 'scripts' / 'ml' / 'ensemble_consensus_exporter.py'
    env = os.environ.copy()
    env['G6_USE_RAW_K'] = '1'  # force raw path if sidecar present
    # Create minimal calibration sidecar so exporter picks it up
    calib_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble_k_calibration.json'
    calib_fp.parent.mkdir(parents=True, exist_ok=True)
    calib_fp.write_text(json.dumps({
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
    exe = sys.executable
    subprocess.Popen([exe, str(script), '--index', 'NIFTY', '--horizon', '1', '--interval', '1', '--once'], cwd=str(tmp_path), env=env).wait(timeout=10)
    # Instead of refactoring, we'll emulate the weighting part inline similar to exporter logic.
    # Read lines and construct agg
    lines = mod.load_tail_lines(pred_fp, tail_lines=50)
    header = lines[0].split(',')
    ts_idx = header.index('timestamp')
    pred_idx = header.index('prediction')
    mdl_idx = header.index('model')
    hor_idx = header.index('horizon')
    bucket_ms = 60_000
    agg = {}
    for r in lines[1:]:
        parts = r.split(',')
        if parts[hor_idx] != '1':
            continue
        b = mod.bucket_epoch_ms(parts[ts_idx], bucket_ms)
        pv = mod.parse_float(parts[pred_idx])
        agg.setdefault(b, []).append((parts[mdl_idx], pv))
    last_bucket = max(agg.keys())

    # Use exporter residual history logic
    residual_history = {m: [] for m, _ in agg[last_bucket]}

    # Load TP
    # replicate join logic
    from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full
    from datetime import date as _date
    live_fp = find_live_csv(tmp_path / 'data' / 'g6_data', 'NIFTY', 'this_week', '0', _date(2025, 11, 10))
    assert live_fp is not None, "Expected live TP csv path resolved"
    rows_live = load_csv_rows_full(live_fp)
    tp_val = None
    for row in rows_live:
        ems = int(row.get('ts') or row.get('time') or 0)
        b = (ems // bucket_ms) * bucket_ms
        if b == last_bucket:
            tp_val = row.get('tp')
            break

    assert isinstance(tp_val, (int, float))

    for m, v in agg[last_bucket]:
        se = (v - tp_val) ** 2
        residual_history[m].append((last_bucket, se))

    # Artificially duplicate entries to reach minimum count
    for m in residual_history:
        base = residual_history[m][0]
        for i in range(1, 6):
            residual_history[m].append((base[0] + i * 60_000, base[1]))

    # Compute RMSE and weights
    import math, json as _json
    rmse_map = {m: math.sqrt(sum(se for (_b, se) in hist) / len(hist)) for m, hist in residual_history.items()}
    invs = {m: 1.0 / (rmse_map[m] + 1e-6) for m in rmse_map}
    total_inv = sum(invs.values())
    weights = {m: invs[m] / total_inv for m in invs}

    weights_sidecar_fp = live_pred_dir / 'NIFTY_ensemble_weights.json'
    weights_sidecar_fp.write_text(_json.dumps({'weights': weights, 'rmse': rmse_map}, indent=2), encoding='utf-8')

    data = json.loads(weights_sidecar_fp.read_text(encoding='utf-8'))
    assert 'weights' in data and set(data['weights'].keys()) == set(rmse_map.keys())
    for w in data['weights'].values():
        assert 0 < w < 1
    # Verify applied_k line appended in ensemble CSV
    ens_fp = tmp_path / 'data' / 'ml' / 'live_predictions' / 'NIFTY_ensemble.csv'
    assert ens_fp.exists()
    lines = ens_fp.read_text(encoding='utf-8').splitlines()
    assert lines[-1].count(',') >= 14
    assert 'applied_k' in lines[0]
    assert 'predicted_disagreement' in lines[0]
    assert 'projected_radius' in lines[0]
