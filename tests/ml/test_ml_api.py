"""
Tests for ML Ensemble API - Phase 4 Implementation

Tests the REST API endpoints for ensemble forecasting.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.web.api.ml_ensemble import create_app, _parse_config


@pytest.fixture
def app():
    """Create Flask test app."""
    test_config_dir = Path(__file__).parent / "test_configs"
    app = create_app(config_dir=test_config_dir)
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get('/health')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['status'] == 'ok'
    assert 'timestamp' in data
    assert data['service'] == 'ml_ensemble_api'


def test_forecast_endpoint_missing_index(client):
    """Test forecast endpoint with missing index parameter."""
    response = client.get('/api/ml/ensemble/forecast')
    assert response.status_code == 400
    
    data = json.loads(response.data)
    assert 'error' in data


def test_forecast_endpoint_invalid_horizon(client):
    """Test forecast endpoint with invalid horizon."""
    response = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=-1')
    assert response.status_code == 400
    
    data = json.loads(response.data)
    assert 'error' in data


def test_forecast_endpoint_success(client):
    """Test forecast endpoint with valid parameters."""
    response = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=60')
    
    # May return 404 if config not found in test environment
    if response.status_code == 404:
        pytest.skip("Config file not available in test environment")
    
    assert response.status_code == 200
    data = json.loads(response.data)
    
    # Check response structure
    assert data['index'] == 'NIFTY'
    assert data['horizon'] == 60
    assert 'timestamp' in data
    assert 'forecast' in data
    assert 'confidence' in data
    assert 'metadata' in data
    
    # Check forecast structure
    forecast = data['forecast']
    assert 'p10' in forecast
    assert 'p50' in forecast
    assert 'p90' in forecast
    assert 'band_low' in forecast
    assert 'band_high' in forecast


def test_diagnostics_endpoint_missing_index(client):
    """Test diagnostics endpoint with missing index."""
    response = client.get('/api/ml/ensemble/diagnostics')
    assert response.status_code == 400


def test_diagnostics_endpoint_success(client):
    """Test diagnostics endpoint with valid parameters."""
    response = client.get('/api/ml/ensemble/diagnostics?index=NIFTY')
    
    if response.status_code == 404:
        pytest.skip("Config file not available in test environment")
    
    assert response.status_code == 200
    data = json.loads(response.data)
    
    # Check response structure
    assert data['index'] == 'NIFTY'
    assert data['status'] in ['healthy', 'degraded', 'error']
    assert 'components' in data
    assert 'weights' in data
    assert 'confidence' in data
    assert 'metrics' in data


def test_confidence_endpoint(client):
    """Test confidence metrics endpoint."""
    response = client.get('/api/ml/ensemble/confidence?index=NIFTY')
    
    if response.status_code == 404:
        pytest.skip("Config file not available in test environment")
    
    assert response.status_code == 200
    data = json.loads(response.data)
    
    assert data['index'] == 'NIFTY'
    assert 'timestamp' in data
    assert 'confidence' in data
    assert 'factors' in data
    assert 'recommendation' in data


def test_retrain_endpoint_missing_index(client):
    """Test retrain endpoint with missing index."""
    response = client.post('/api/ml/ensemble/retrain',
                          json={})
    assert response.status_code == 400


def test_retrain_endpoint_success(client):
    """Test retrain endpoint with valid parameters."""
    response = client.post('/api/ml/ensemble/retrain',
                          json={'index': 'NIFTY', 'days': 60, 'validate': True})
    
    assert response.status_code == 200
    data = json.loads(response.data)
    
    assert data['index'] == 'NIFTY'
    assert data['status'] == 'scheduled'
    assert 'job_id' in data
    assert 'parameters' in data
    assert data['parameters']['training_days'] == 60


def test_parse_config():
    """Test configuration parsing."""
    config_data = {
        'components': {
            'baseline': {'enabled': True, 'k_coefficient': 1.0},
            'gbrt': {'enabled': True, 'model_path': 'models/test/'},
            'retrieval': {'enabled': True, 'k': 20, 'window': 60},
            'conformal': {'enabled': True, 'target_coverage': 0.8}
        },
        'weighting': {
            'strategy': 'confidence_adaptive',
            'confidence_threshold': 0.7,
            'weights_high_confidence': {'gbrt': 0.8, 'retrieval': 0.2},
            'weights_low_confidence': {'gbrt': 0.5, 'retrieval': 0.5}
        }
    }
    
    config = _parse_config(config_data)
    
    assert config.baseline_enabled is True
    assert config.gbrt_enabled is True
    assert config.retrieval_enabled is True
    assert config.conformal_enabled is True
    assert config.baseline_k == 1.0
    assert config.retrieval_k == 20
    assert config.conformal_target_coverage == 0.8
    assert config.weighting_strategy == 'confidence_adaptive'
    assert config.confidence_threshold == 0.7


def test_parse_config_defaults():
    """Test configuration parsing with minimal data."""
    config_data = {}
    
    config = _parse_config(config_data)
    
    # Should have sensible defaults
    assert config.baseline_enabled is True
    assert config.retrieval_k == 20
    assert config.conformal_target_coverage == 0.8


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
