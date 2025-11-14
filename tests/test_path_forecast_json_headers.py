import pytest
from fastapi.testclient import TestClient


def test_path_forecast_json_headers_parity(monkeypatch, tmp_path):
    """Ensure JSON route exposes expected retrieval/profile headers matching diagnostics fields.
    We monkeypatch the live loader helper to inject synthetic rows and a controlled now timestamp.
    """
    # Import after monkeypatch path to avoid early imports failing
    from src.web.dashboard.routes import path_forecast as pf
    from src.web.dashboard.app import app

    now_ms = 1731043200000  # 2025-11-08 00:00:00 UTC

    # Synthetic live rows: each dict contains minimal fields for extract_tp
    rows = [
        {"ts": now_ms - 60000 * i, "tp": float(100.0 + i * 0.5)} for i in range(30)
    ]
    rows.sort(key=lambda r: r["ts"])  # ascending chronological order

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
            "window": 10,
            "k": 5,
            "mode": "retrieval",
            "profile": "base",
            # force disable cache to exercise fresh pipeline path in synthetic context
            "no_cache": True,
        },
    )
    assert resp.status_code == 200

    # Headers we expect to exist (may be empty strings but should be present)
    expected_headers = [
        "X-Retrieval-Pruned",
        "X-Retrieval-Retained",
        "X-Retrieval-RegimePenalized",
        "X-Retrieval-AnnEnabled",
        "X-Retrieval-AnnTotalWindows",
        "X-Retrieval-AnnShortlisted",
        "X-Cache-Entries",
        "X-Cache-Hits",
        "X-Cache-Misses",
        "X-Cache-Evictions",
        "X-Retrieval-Distance",
        "X-Retrieval-WeightMode",
        "X-PathForecast-RequestedMode",
        "X-Gen-Ms",
        "X-Gen-Iso",
        "X-Time-Align",
        "X-Route-Version",
    ]
    for h in expected_headers:
        assert h in resp.headers, f"missing header: {h}"

    # Profile echo headers
    for h in [
        "X-Profile",
        "X-Profile-Distance",
        "X-Profile-WeightMode",
    ]:
        assert h in resp.headers, f"missing profile header: {h}"

    # Basic payload sanity: list of dict with required keys
    data = resp.json()
    assert isinstance(data, list)
    if data:  # allow empty when horizon or rows insufficient
        row = data[0]
        for k in ["plot_time", "q10", "q50", "q90"]:
            assert k in row

