import json
import sys
from pathlib import Path


def _write_predictions(fp: Path, ts: str = "2025-11-11 10:00:00"):
    fp.write_text(
        "\n".join([
            "timestamp,prediction,model,index,horizon",
            f"{ts},100.0,sk_hgb_regressor,NIFTY,1",
            f"{ts},102.0,xgb_regressor,NIFTY,1",
        ]),
        encoding="utf-8",
    )


def _write_calibration(fp: Path):
    fp.write_text(json.dumps({
        'timestamp': 0,
        'recommended_k': 1.20,
        'k_smooth': 1.15,
        'effective_cov': 0.81,
        'band_radius': 11.0,
        'target': 0.8,
        'index': 'NIFTY',
        'horizon': '1',
        'n': 42
    }, indent=2), encoding='utf-8')


def test_forecast_columns_and_values(tmp_path, monkeypatch):
    # Monkeypatch project_root
    import importlib
    exporter = importlib.import_module('scripts.ml.ensemble_consensus_exporter')
    from src.web.dashboard.core import paths as real_paths

    def fake_root():
        return tmp_path

    monkeypatch.setattr(real_paths, 'project_root', fake_root, raising=True)

    base = tmp_path / 'data' / 'ml' / 'live_predictions'
    base.mkdir(parents=True, exist_ok=True)
    pred_fp = base / 'NIFTY.csv'
    _write_predictions(pred_fp)
    _write_calibration(base / 'NIFTY_ensemble_k_calibration.json')

    # Run exporter once (EMA forecast first step falls back to current disagreement)
    monkeypatch.setattr(sys, 'argv', [exporter.__file__, '--index', 'NIFTY', '--horizon', '1', '--once'])
    exporter.main()

    ens_fp = base / 'NIFTY_ensemble.csv'
    text = ens_fp.read_text(encoding='utf-8').splitlines()
    header = text[0].split(',')
    assert 'predicted_disagreement' in header
    assert 'projected_radius' in header
    last = text[-1].split(',')
    h_index = {c: i for i, c in enumerate(header)}
    dis = float(last[h_index['disagreement']])
    pred_dis = float(last[h_index['predicted_disagreement']])
    proj_r = float(last[h_index['projected_radius']])
    applied_k = float(last[h_index['applied_k']])
    # First cycle prediction should equal current dis (fallback)
    assert abs(pred_dis - dis) <= 1e-9
    # Projected radius should be >= applied_k * pred_dis
    assert proj_r >= applied_k * pred_dis - 1e-9
