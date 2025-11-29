"""Test SSE drift stream endpoint basic behavior."""
from __future__ import annotations
import pytest
from flask import Flask
from typing import Iterator

from src.web.api.ml_ensemble import create_app

@pytest.fixture(scope="module")
def app() -> Flask:
    a = create_app()
    a.config['TESTING'] = True
    return a

@pytest.fixture()
def client(app):
    return app.test_client()

@pytest.mark.timeout(5)
def test_drift_stream_smoke(client):
    resp = client.get('/api/ml/ensemble/drift_stream?index=NIFTY&max_events=2&interval_ms=250')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    # Expect at least one drift event
    assert 'event: drift' in text
    # JSON payload should include index field
    assert '"index":"NIFTY"' in text
    # End event marker when bounded
    assert 'event: end' in text or 'max_events=0' in text  # allow variability
