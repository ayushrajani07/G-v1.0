"""Tests for /api/ml/ensemble/weights endpoint.

Strategy:
1. Monkeypatch project_root() so endpoint reads from a temp directory.
2. Create sidecar JSON <INDEX>_ensemble_weights.json with known weights/rmse.
3. Hit endpoint with TestClient and assert:
   - 200 OK
   - Header matches expected columns
   - Rows sorted by weight descending (since implementation sorts)
   - Each row includes index and horizon columns and formatted floats.
Edge Cases Covered:
 - Missing file returns 404
 - Non-numeric weights still handled (fallback to 0.0) -> simulated with one bad value
"""

import json
from pathlib import Path
from fastapi.testclient import TestClient

from src.web.dashboard.app import app
from src.web.dashboard.core import paths as real_paths


client = TestClient(app)


def _write_sidecar(tmp_path: Path, index: str):
    data = {
        "timestamp": "2025-11-10T10:00:00",
        "weights": {
            "model_a": 0.7,
            "model_b": 0.2,
            "model_c": "not-a-number",  # should degrade to 0.0
            "model_d": 0.1,
        },
        "rmse": {
            "model_a": 12.34,
            "model_b": 22.22,
            "model_c": 30.0,
            "model_d": 40.0,
        },
    }
    base = tmp_path / "data" / "ml" / "live_predictions"
    base.mkdir(parents=True, exist_ok=True)
    fp = base / f"{index}_ensemble_weights.json"
    fp.write_text(json.dumps(data), encoding="utf-8")
    return fp


def test_ensemble_weights_happy_path(tmp_path, monkeypatch):  # type: ignore
    index = "NIFTY"

    def fake_project_root():  # override to temp directory
        return tmp_path

    monkeypatch.setattr(real_paths, "project_root", fake_project_root, raising=True)
    _write_sidecar(tmp_path, index)

    resp = client.get(f"/api/ml/ensemble/weights?index={index}&horizon=1")
    assert resp.status_code == 200, resp.text
    text = resp.text.strip().splitlines()
    assert text, "Empty CSV response"
    header = text[0]
    assert header == "timestamp,model,weight,rmse,index,horizon"
    rows = text[1:]
    # Expect 4 rows, sorted by weight desc (model_a 0.7, model_b 0.2, model_d 0.1, model_c 0.0)
    assert len(rows) == 4
    models_in_order = [r.split(",")[1] for r in rows]
    assert models_in_order == ["model_a", "model_b", "model_d", "model_c"], models_in_order
    # Check numeric formatting (6 decimals) for weight and rmse
    for r in rows:
        parts = r.split(",")
        assert len(parts) == 6, f"Row should have 6 columns: {r}"
        ts, m, w, rmse, idx, horizon = parts
        assert idx == index
        assert horizon == "1"
        assert ts == "2025-11-10T10:00:00"
        assert "." in w and len(w.split(".")[-1]) == 6, f"Weight not formatted to 6 decimals: {w}"
        assert "." in rmse and len(rmse.split(".")[-1]) == 6, f"RMSE not formatted to 6 decimals: {rmse}"


def test_ensemble_weights_missing_sidecar(tmp_path, monkeypatch):  # type: ignore
    index = "NIFTY"

    def fake_project_root():
        return tmp_path

    monkeypatch.setattr(real_paths, "project_root", fake_project_root, raising=True)
    # No file written
    resp = client.get(f"/api/ml/ensemble/weights?index={index}&horizon=1")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()
