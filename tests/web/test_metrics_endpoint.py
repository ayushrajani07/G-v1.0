from fastapi.testclient import TestClient


def _make_client():
    from src.web.dashboard.app import app
    return TestClient(app)


def test_metrics_disabled(monkeypatch):
    monkeypatch.delenv("ENABLE_PATH_FORECAST_PROM_METRICS", raising=False)
    client = _make_client()
    r = client.get("/metrics")
    assert r.status_code == 503


def test_metrics_enabled_live_mae(monkeypatch):
    monkeypatch.setenv("ENABLE_PATH_FORECAST_PROM_METRICS", "1")
    monkeypatch.setenv("ENABLE_STREAM_INGEST", "1")
    client = _make_client()
    # Ingest a sample to update live MAE
    client.post("/api/stream/ingest", json={"y_true": 100.0, "y_pred": 99.0})
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "g6_live_mae" in body