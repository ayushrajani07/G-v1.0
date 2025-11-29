from fastapi.testclient import TestClient


def _client():
    from src.web.dashboard.app import app
    return TestClient(app)


def test_prometheus_drift_metrics_index_label(monkeypatch):
    monkeypatch.setenv("ENABLE_STREAM_INGEST", "1")
    monkeypatch.setenv("ENABLE_PATH_FORECAST_PROM_METRICS", "1")
    c = _client()
    # Trigger SSE drift emission for index=NIFTY
    with c.stream("GET", "/api/stream/sse/live?interval_ms=10&index=NIFTY&window=15") as r:
        # Read a few chunks then close
        for _ in range(5):
            next(r.iter_text())
    # Fetch metrics
    resp = c.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    # Expect labeled drift metrics
    assert 'g6_drift_mae{' in body
    assert 'g6_drift_mape{' in body
    assert 'g6_drift_status{' in body
    # At least one line contains index="NIFTY"
    assert 'index="NIFTY"' in body
