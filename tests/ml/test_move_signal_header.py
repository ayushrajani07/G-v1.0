from __future__ import annotations

from pathlib import Path
import asyncio
import joblib  # type: ignore

from src.web.dashboard.core import paths as _paths  # type: ignore
from src.web.dashboard.core.csv_io import load_csv_rows_full  # type: ignore


def test_move_exporter_writes_header_and_row(tmp_path: Path, monkeypatch):
    # Arrange: fake project_root
    monkeypatch.setattr(_paths, "project_root", lambda: tmp_path)
    data_lp = tmp_path / "data" / "ml" / "live_predictions"
    data_lp.mkdir(parents=True, exist_ok=True)
    g6 = tmp_path / "data" / "g6_data"
    g6.mkdir(parents=True, exist_ok=True)

    # Minimal live csv with two rows
    live_fp = g6 / "TEST_this_week_0.csv"
    live_fp.write_text("ts,tp,index_price,minutes_to_expiry,ce_iv,pe_iv,tp_net_change,tp_day_change\n"
                       "1700000000000,100,20000,300,0.2,0.2,0,0\n"
                       "1700000060000,102,20010,299,0.21,0.2,2,2\n", encoding="utf-8")

    # Dummy classifier/regressor artifacts
    class DummyClf:
        def predict_proba(self, X):
            import numpy as np
            return np.array([[0.3, 0.7]])
    class DummyReg:
        def predict(self, X):
            return [5.0]
    clf_art = {"model": DummyClf(), "features": [
        "index_price", "minutes_to_expiry", "ce_iv", "pe_iv", "tp", "tp_net_change", "tp_day_change"
    ]}
    reg_art = {"model": DummyReg(), "features": clf_art["features"], "mean_magnitude": 4.0}
    clf_path = tmp_path / "clf.joblib"
    reg_path = tmp_path / "reg.joblib"
    joblib.dump(clf_art, clf_path)
    joblib.dump(reg_art, reg_path)

    # Config
    import json as _json
    cfg = tmp_path / "cfg.json"
    cfg_payload = {
        "features": ["index_price", "minutes_to_expiry", "ce_iv", "pe_iv", "tp", "tp_net_change", "tp_day_change"],
        "inference": {"prob_threshold": 0.6}
    }
    cfg.write_text(_json.dumps(cfg_payload), encoding="utf-8")

    # Act: run exporter once by importing main and invoking in-process with arguments
    import subprocess, sys
    exe = sys.executable
    script = tmp_path.parents[0] / "scripts" / "ml" / "move_predict_exporter.py"
    # If script path differs in CI, construct explicitly
    script = Path("c:/Users/Asus/Desktop/g6_reorganized/scripts/ml/move_predict_exporter.py") if not script.exists() else script
    # Run a single iteration by relying on two rows and then break via timeout
    proc = subprocess.Popen([exe, str(script), "--config", str(cfg), "--classifier-artifact", str(clf_path), "--regressor-artifact", str(reg_path), "--index", "TEST", "--horizon", "1", "--interval", "1", "--expiry-tag", "this_week", "--offset", "0"], cwd=str(tmp_path))
    try:
        proc.wait(timeout=3)
    except Exception:
        proc.terminate()

    # Assert: output file exists and has header
    out_fp = data_lp / "TEST_move.csv"
    assert out_fp.exists(), "exporter did not create output file"
    lines = out_fp.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].startswith("timestamp,move_prob,move_label_pred,conditional_magnitude,model,index,horizon"), lines[:2]
    assert len(lines) >= 2
