from __future__ import annotations
import os
import pytest
from src.web.api.ml_ensemble import create_app

@pytest.fixture(scope="module")
def app():
    a = create_app()
    a.config['TESTING'] = True
    return a

@pytest.fixture()
def client(app):
    return app.test_client()

@pytest.mark.timeout(5)
def test_latency_anomaly_basic(client, monkeypatch):
    monkeypatch.setenv('ENABLE_ML_QUALITY_METRICS', '1')
    # Warm buffer with several calls
    for _ in range(25):
        r = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=60')
        assert r.status_code == 200
    # Final call should include anomaly score in metadata
    r = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=60')
    body = r.get_json()
    assert 'latency_anomaly_score' in body.get('metadata', {})
