from fastapi.testclient import TestClient


def _client():
    from src.web.dashboard.app import app
    return TestClient(app)


def test_sse_consolidated_params(monkeypatch):
    monkeypatch.setenv("ENABLE_STREAM_INGEST", "1")
    c = _client()
    # seed observations
    c.post("/api/stream/ingest", json={"y_true": 100.0, "y_pred": 99.0})
    with c.stream("GET", "/api/stream/sse/live?interval_ms=10&index=NIFTY&window=15") as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            if "event: drift" in buf and '"window": 15' in buf and '"index": "NIFTY"' in buf:
                break
            if len(buf) > 20000:
                break
    assert "event: drift" in buf
    assert '"window": 15' in buf
    assert '"index": "NIFTY"' in buf
