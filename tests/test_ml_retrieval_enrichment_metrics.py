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
def test_retrieval_enrichment_metrics_exposed(client, monkeypatch):
    monkeypatch.setenv('ENABLE_ML_QUALITY_METRICS', '1')
    # Call forecast to push metrics and include metadata
    r = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=60')
    assert r.status_code == 200
    body = r.get_json()
    md = body.get('metadata', {})
    assert 0.0 <= md.get('retrieval_success_ratio', 0.0) <= 1.0
    assert 0.0 <= md.get('feature_completeness_ratio', 0.0) <= 1.0
