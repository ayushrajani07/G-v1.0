from fastapi.testclient import TestClient


def _client():
    from src.web.dashboard.app import app
    return TestClient(app)


def test_prometheus_drift_metrics_index_horizon_labels(monkeypatch):
    monkeypatch.setenv("ENABLE_STREAM_INGEST", "1")
    monkeypatch.setenv("ENABLE_PATH_FORECAST_PROM_METRICS", "1")
    c = _client()
    # Trigger SSE drift emission for index=NIFTY horizon=120
    with c.stream("GET", "/api/stream/sse/live?interval_ms=10&index=NIFTY&window=15&horizon=120") as r:
        # Consume a few chunks to allow emission
        for _ in range(5):
            next(r.iter_text())
    metrics = c.get("/metrics")
    assert metrics.status_code == 200
    body = metrics.text
    # Verify labels present with horizon
    assert 'g6_drift_mae{' in body
    assert 'index="NIFTY"' in body
    assert 'horizon="120"' in body
