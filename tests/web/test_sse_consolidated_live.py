from fastapi.testclient import TestClient


def _client():
    from src.web.dashboard.app import app
    return TestClient(app)


def test_sse_consolidated_stream(monkeypatch):
    monkeypatch.setenv("ENABLE_STREAM_INGEST", "1")
    c = _client()
    # seed one observation
    c.post("/api/stream/ingest", json={"y_true": 100.0, "y_pred": 99.5})
    with c.stream("GET", "/api/stream/sse/live?interval_ms=10") as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            if "event: live_mae" in buf and "event: drift" in buf:
                break
            if len(buf) > 20000:
                break
    assert "event: live_mae" in buf
    assert "event: drift" in buf
