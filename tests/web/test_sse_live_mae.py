import time
from fastapi.testclient import TestClient


def _client():
    from src.web.dashboard.app import app
    return TestClient(app)


def test_sse_live_mae_stream(monkeypatch):
    monkeypatch.setenv("ENABLE_STREAM_INGEST", "1")
    c = _client()
    # Ensure feedback has at least one observation
    c.post("/api/stream/ingest", json={"y_true": 101.0, "y_pred": 99.0})
    with c.stream("GET", "/api/stream/sse/live_mae?interval_ms=10") as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            if "event: live_mae" in buf and "data:" in buf:
                break
            # guard to avoid hanging in CI
            if len(buf) > 10000:
                break
    assert "event: live_mae" in buf
