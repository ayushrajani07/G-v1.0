"""Tests for regime detection API endpoints (Phase 10)"""

from __future__ import annotations

import os
from typing import Any

import pytest

# Test will require fastapi test client
try:
    from fastapi.testclient import TestClient
except ImportError:
    pytest.skip("fastapi not available", allow_module_level=True)

from src.ml import regime_detector


def test_regime_endpoint_basic(monkeypatch):
    """Test basic regime endpoint functionality."""
    # Create test data
    test_index = f"TEST_ENDPOINT_{os.getpid()}"
    
    # Create and store a regime history entry
    embedding = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.5,
        bandwidth=0.3,
        drift_severity=0.2,
        cache_hit_ratio=0.8,
        norm_error_p90=0.15,
    )
    
    regime_detector.update_regime_history(
        test_index,
        embedding,
        regime_detector.REGIME_STATUS_STABLE,
        0.0,
    )
    
    # Import app and create test client
    from src.web.dashboard.app import app
    client = TestClient(app)
    
    # Test regime endpoint
    response = client.get(f"/api/ml/ensemble/regime?index={test_index}")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check response structure
    assert "embedding" in data
    assert "distance" in data
    assert "shift_status" in data
    assert "last_change_timestamp" in data
    assert "history_count" in data
    
    # Check values
    assert data["shift_status"] == "stable"
    assert data["distance"] == 0.0
    assert data["history_count"] == 1
    
    # Clean up
    try:
        path = regime_detector._get_history_path(test_index)
        if path.exists():
            path.unlink()
            path.parent.rmdir()
    except Exception:
        pass


def test_regime_endpoint_no_history():
    """Test regime endpoint with no history (should return default values)."""
    test_index = f"TEST_NO_HISTORY_EP_{os.getpid()}"
    
    from src.web.dashboard.app import app
    client = TestClient(app)
    
    response = client.get(f"/api/ml/ensemble/regime?index={test_index}")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["embedding"] == {}
    assert data["distance"] == 0.0
    assert data["shift_status"] == "stable"
    assert data["history_count"] == 0


def test_metrics_compare_includes_regime():
    """Test that metrics/compare includes regime information when index is specified."""
    test_index = f"TEST_METRICS_{os.getpid()}"
    
    # Create test regime data
    embedding = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.4,
        bandwidth=0.3,
        drift_severity=0.2,
        cache_hit_ratio=0.75,
        norm_error_p90=0.2,
    )
    
    regime_detector.update_regime_history(
        test_index,
        embedding,
        regime_detector.REGIME_STATUS_WARN,
        0.25,
    )
    
    from src.web.dashboard.app import app
    client = TestClient(app)
    
    # Test metrics/compare endpoint with index filter
    response = client.get(f"/api/ml/ensemble/metrics/compare?index={test_index}")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check that regime fields are present
    assert "regime_status" in data
    assert "regime_distance" in data
    
    # Check values match what we set
    assert data["regime_status"] == "warn"
    assert data["regime_distance"] == 0.25
    
    # Clean up
    try:
        path = regime_detector._get_history_path(test_index)
        if path.exists():
            path.unlink()
            path.parent.rmdir()
    except Exception:
        pass


def test_metrics_compare_without_index():
    """Test that metrics/compare works without index (no regime info)."""
    from src.web.dashboard.app import app
    client = TestClient(app)
    
    # Test without index parameter
    response = client.get("/api/ml/ensemble/metrics/compare")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should not have regime fields if no index specified
    # (The actual response structure depends on the rolling_mae module,
    # but regime fields should only be present when index is specified)
    # We're just checking it doesn't error
    assert isinstance(data, dict)
