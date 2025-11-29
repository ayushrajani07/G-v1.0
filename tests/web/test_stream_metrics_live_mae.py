from fastapi.testclient import TestClient


def _client():
    from src.web.dashboard.app import app
    return TestClient(app)


def test_live_mae_metrics_json(monkeypatch):
    # Enable ingest and metrics
    monkeypatch.setenv("ENABLE_STREAM_INGEST", "1")
    monkeypatch.setenv("ENABLE_PATH_FORECAST_PROM_METRICS", "1")
    # Low threshold to force alert increment
    monkeypatch.setenv("LIVE_MAE_ALERT_THRESHOLD", "0.0")

    c = _client()
    # Post sample
    c.post("/api/stream/ingest", json={"y_true": 101.0, "y_pred": 99.0})
    # Read JSON metrics
    r = c.get("/api/stream/metrics/live_mae")
    assert r.status_code == 200
    body = r.json()
    assert body.get("observations", 0) >= 1
    assert isinstance(body.get("mae"), float)

    # Confirm Prometheus endpoint has both metrics
    mr = c.get("/metrics")
    assert mr.status_code == 200
    txt = mr.text
    assert "g6_live_mae" in txt
    assert "g6_live_mae_alerts_total" in txt
