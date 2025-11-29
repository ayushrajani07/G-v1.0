"""Test config integrity endpoint behavior."""
from __future__ import annotations
import os
import pytest
from flask import Flask
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
def test_config_integrity_missing(client):
    # No signature yet for UNKNOWN
    r = client.get('/api/ml/ensemble/config_integrity?index=UNKNOWN')
    assert r.status_code == 404
    body = r.get_json()
    assert body['signed'] is False

@pytest.mark.timeout(5)
def test_config_integrity_signed(client, monkeypatch):
    # Provide signing key then access a known config (if exists)
    monkeypatch.setenv('CONFIG_SIGNING_KEY', 'test-secret-key')
    # Trigger load of config by calling diagnostics (will attempt to load config file)
    client.get('/api/ml/ensemble/diagnostics?index=NIFTY')
    r = client.get('/api/ml/ensemble/config_integrity?index=NIFTY')
    # If config exists we expect 200; if not present test is skipped gracefully
    if r.status_code == 404:
        pytest.skip('NIFTY config not present; integrity not recorded')
    body = r.get_json()
    assert body['signed'] is True
    assert 'signature' in body and isinstance(body['signature'], str) and len(body['signature']) >= 40
