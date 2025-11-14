import pytest
from fastapi.testclient import TestClient


def test_path_forecast_json_ann_headers(monkeypatch):
    """Verify ANN-related headers surface when use_ann is enabled.
    Uses synthetic rows; ANN may fallback internally but should set ann_enabled flag.
    """
    from src.web.dashboard.routes import path_forecast as pf
    from src.web.dashboard.app import app

    now_ms = 1731043200000  # arbitrary stable timestamp
    # Build synthetic increasing tp values to satisfy window
    rows = [
        {"ts": now_ms - 60000 * (60 - i), "tp": 100.0 + i * 0.1} for i in range(60)
    ]  # 60 rows with 'ts' to match loader

    def fake_load_live_rows_and_context(request, index, expiry_tag, offset, date_str, now_override_ms):
        last_tp = rows[-1]["tp"]
        return rows, last_tp, now_ms, (expiry_tag or "this_week"), pf._dt.date(2025, 11, 8)

    monkeypatch.setattr(pf, "_load_live_rows_and_context", fake_load_live_rows_and_context, raising=True)

    client = TestClient(app)
    resp = client.get(
        "/api/ml/path_forecast_json",
        params={
            "index": "NIFTY",
            "horizon_minutes": 30,
            "window": 30,
            "k": 5,
            "mode": "retrieval",
            "use_ann": True,
            "ann_space": "cosine",
            "ann_max_candidates": 10,
        },
    )
    assert resp.status_code == 200
    # ANN headers present
    for h in ["X-Retrieval-AnnEnabled", "X-Retrieval-AnnTotalWindows", "X-Retrieval-AnnShortlisted"]:
        assert h in resp.headers, f"missing ANN header {h}"
    # Enabled flag should be truthy string ("True" or "1")
    assert resp.headers.get("X-Retrieval-AnnEnabled") in {"True", "true", "1"}
