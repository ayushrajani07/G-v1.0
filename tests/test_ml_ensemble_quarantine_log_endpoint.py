"""Tests for /api/ml/ensemble/quarantine_log endpoint.

Strategy:
1. Monkeypatch project_root() so endpoint reads from a temp directory.
2. Create quarantine log <INDEX>_ensemble_quarantine.log with mixed horizons and events.
3. Hit endpoint with TestClient and assert:
   - 200 OK
   - Header matches expected columns
   - Tail limiting respected
   - Horizon filter works (returns only matching rows)
Edge Cases:
 - Missing file returns 404
 - Lines with minimal fields are skipped gracefully
"""

from pathlib import Path
from fastapi.testclient import TestClient

from src.web.dashboard.app import app
from src.web.dashboard.core import paths as real_paths


client = TestClient(app)


def _write_log(tmp_path: Path, index: str):
    base = tmp_path / "data" / "ml" / "live_predictions"
    base.mkdir(parents=True, exist_ok=True)
    fp = base / f"{index}_ensemble_quarantine.log"
    lines = [
        # timestamp,event,model, extras (z, dis, until, horizon)
        "2025-11-10T09:00:00,QUARANTINE,model_a,z=3.2,dis=1.5,until=1731234567000,horizon=1",
        "2025-11-10T09:10:00,UNQUARANTINE,model_a,z=1.0,dis=0.5,until=0,horizon=1",
        "2025-11-10T09:20:00,QUARANTINE,model_b,z=2.8,dis=2.0,until=1731239999000,horizon=5",
        # malformed/short line (should be skipped silently)
        "badline,onlytwo",
        # another valid row for horizon=1
        "2025-11-10T09:30:00,QUARANTINE,model_c,z=2.0,dis=0.8,until=1731240000000,horizon=1",
    ]
    fp.write_text("\n".join(lines), encoding="utf-8")
    return fp


def test_quarantine_log_happy_path_and_filters(tmp_path, monkeypatch):  # type: ignore
    index = "NIFTY"

    def fake_project_root():
        return tmp_path

    monkeypatch.setattr(real_paths, "project_root", fake_project_root, raising=True)
    _write_log(tmp_path, index)

    # No horizon filter, default tail=200
    r1 = client.get(f"/api/ml/ensemble/quarantine_log?index={index}")
    assert r1.status_code == 200, r1.text
    lines = r1.text.strip().splitlines()
    assert lines[0] == "timestamp,event,model,z,dis,until_ms,horizon"
    # We wrote 5 lines but one is malformed -> expect 4 data rows + header
    assert len(lines) == 1 + 4

    # Horizon filter: horizon=1 should include only rows with h=1
    r2 = client.get(f"/api/ml/ensemble/quarantine_log?index={index}&horizon=1")
    assert r2.status_code == 200, r2.text
    rows_h1 = r2.text.strip().splitlines()[1:]
    assert rows_h1, "Expected rows for horizon=1"
    for r in rows_h1:
        assert r.endswith(",1"), f"Row should be for horizon=1: {r}"
    # Should exclude model_b h=5 row
    assert all("model_b" not in r for r in rows_h1)

    # Tail limiting: ask for tail=2 -> expect last two valid lines only
    r3 = client.get(f"/api/ml/ensemble/quarantine_log?index={index}&tail=2")
    assert r3.status_code == 200, r3.text
    data_tail2 = r3.text.strip().splitlines()[1:]
    assert len(data_tail2) == 2
    # last two valid lines in file are the malformed one (skipped) then the last QUARANTINE
    # so we expect the last two valid: QUARANTINE model_b (h=5) and QUARANTINE model_c (h=1)
    assert "model_b" in data_tail2[0]
    assert "model_c" in data_tail2[1]


def test_quarantine_log_missing(tmp_path, monkeypatch):  # type: ignore
    index = "NIFTY"

    def fake_project_root():
        return tmp_path

    monkeypatch.setattr(real_paths, "project_root", fake_project_root, raising=True)
    # No file written
    r = client.get(f"/api/ml/ensemble/quarantine_log?index={index}")
    assert r.status_code == 404
    assert "not found" in r.text.lower()
