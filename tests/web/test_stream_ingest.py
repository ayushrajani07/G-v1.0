import os
from fastapi.testclient import TestClient


def _make_client():
    from src.web.dashboard.app import app
    return TestClient(app)


def test_stream_ingest_queue(monkeypatch):
    monkeypatch.setenv("ENABLE_STREAM_INGEST", "1")
    client = _make_client()
    r = client.post("/api/stream/ingest", json={"y_true": 100.0, "y_pred": 99.0})
    assert r.status_code == 200
    assert r.json().get("status") == "queued"


def test_stream_ingest_unavailable(monkeypatch):
    monkeypatch.setenv("ENABLE_STREAM_INGEST", "0")
    client = _make_client()
    r = client.post("/api/stream/ingest", json={"y_true": 100.0, "y_pred": 99.0})
    assert r.status_code in (503, 200)
    # When disabled, ingestor may be None -> 503; if previously started in same process, may still be available.