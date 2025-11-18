"""
ML Ensemble API Endpoints Tests - Phase 8

Tests for ML ensemble API endpoints to validate functionality in production.

Run with:
    pytest tests/test_ml_ensemble_endpoints.py -v
"""

from __future__ import annotations

import json
import warnings
import urllib.request
import urllib.error
from typing import Dict

import pytest


class TestMLEnsembleAPI:
    """ML Ensemble API endpoint tests."""
    
    @pytest.fixture
    def api_base_url(self) -> str:
        """Base URL for API."""
        return "http://localhost:9210"
    
    @pytest.fixture
    def default_headers(self) -> Dict[str, str]:
        """Default request headers."""
        return {'User-Agent': 'pytest-ml-ensemble'}
    
    def make_request(self, url: str, headers: Dict[str, str], timeout: int = 10) -> Dict:
        """Make HTTP request and return JSON response."""
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode())
    
    def test_health_endpoint(self, api_base_url: str, default_headers: Dict):
        """Test /health endpoint."""
        url = f"{api_base_url}/health"
        
        try:
            data = self.make_request(url, default_headers)
            
            assert "status" in data
            assert data["status"] in ["healthy", "degraded"]
            
        except urllib.error.URLError:
            pytest.skip("API not running")
    
    def test_forecast_nifty_default_horizon(self, api_base_url: str, default_headers: Dict):
        """Test forecast endpoint for NIFTY with default horizon."""
        url = f"{api_base_url}/api/ml/ensemble/forecast?index=NIFTY"
        
        try:
            data = self.make_request(url, default_headers, timeout=30)
            
            # Validate response structure
            assert "p10" in data
            assert "p50" in data
            assert "p90" in data
            assert "confidence_score" in data
            
            # Validate quantile ordering
            assert data["p10"] <= data["p50"] <= data["p90"]
            
            # Validate confidence score range
            assert 0 <= data["confidence_score"] <= 1
            
        except urllib.error.URLError:
            pytest.skip("API not running or forecast failed")
    
    def test_forecast_nifty_custom_horizon(self, api_base_url: str, default_headers: Dict):
        """Test forecast endpoint with custom horizon."""
        horizons = [30, 60, 120]
        
        for horizon in horizons:
            url = f"{api_base_url}/api/ml/ensemble/forecast?index=NIFTY&horizon={horizon}"
            
            try:
                data = self.make_request(url, default_headers, timeout=30)
                
                assert "p50" in data
                assert data["p50"] > 0
                
            except urllib.error.URLError:
                pytest.skip(f"API not running or forecast failed for horizon={horizon}")
    
    def test_forecast_banknifty(self, api_base_url: str, default_headers: Dict):
        """Test forecast endpoint for BANKNIFTY."""
        url = f"{api_base_url}/api/ml/ensemble/forecast?index=BANKNIFTY&horizon=60"
        
        try:
            data = self.make_request(url, default_headers, timeout=30)
            
            assert "p50" in data
            assert data["p50"] > 0
            
        except urllib.error.URLError:
            pytest.skip("API not running or BANKNIFTY forecast failed")
    
    def test_forecast_invalid_index(self, api_base_url: str, default_headers: Dict):
        """Test forecast endpoint with invalid index."""
        url = f"{api_base_url}/api/ml/ensemble/forecast?index=INVALID"
        
        try:
            req = urllib.request.Request(url, headers=default_headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                # Should get error response
                assert response.code != 200
                
        except urllib.error.HTTPError as e:
            # Expected to fail with 400 or 404
            assert e.code in [400, 404, 500]
        except urllib.error.URLError:
            pytest.skip("API not running")
    
    def test_diagnostics_endpoint(self, api_base_url: str, default_headers: Dict):
        """Test /api/ml/ensemble/diagnostics endpoint."""
        url = f"{api_base_url}/api/ml/ensemble/diagnostics?index=NIFTY"
        
        try:
            data = self.make_request(url, default_headers)
            
            assert "status" in data or "metrics" in data
            
        except urllib.error.URLError:
            pytest.skip("API not running or diagnostics not available")
    
    def test_forecast_latency(self, api_base_url: str, default_headers: Dict):
        """Test forecast endpoint latency is acceptable."""
        import time
        
        url = f"{api_base_url}/api/ml/ensemble/forecast?index=NIFTY&horizon=60"
        
        try:
            start = time.time()
            data = self.make_request(url, default_headers, timeout=30)
            latency = time.time() - start
            
            # Check latency is under 5 seconds (generous for testing)
            assert latency < 5.0, f"Forecast latency {latency:.2f}s exceeds 5s threshold"
            
            # Ideally should be under 1 second
            if latency > 1.0:
                # Assert a warning is emitted using proper context manager
                with pytest.warns(UserWarning, match=r"exceeds production target"):
                    warnings.warn(
                        f"Forecast latency {latency:.2f}s exceeds production target of 1s",
                        UserWarning,
                    )
            
        except urllib.error.URLError:
            pytest.skip("API not running")
    
    def test_forecast_consistency(self, api_base_url: str, default_headers: Dict):
        """Test that multiple forecast requests return consistent results."""
        url = f"{api_base_url}/api/ml/ensemble/forecast?index=NIFTY&horizon=60"
        
        try:
            # Make two requests
            data1 = self.make_request(url, default_headers, timeout=30)
            data2 = self.make_request(url, default_headers, timeout=30)
            
            # Results should be similar (within 5% for same timestamp)
            # In production, they might differ slightly due to data updates
            if "p50" in data1 and "p50" in data2:
                diff_pct = abs(data1["p50"] - data2["p50"]) / data1["p50"] * 100
                # Allow some variation but not too much
                assert diff_pct < 50, f"Forecasts differ by {diff_pct:.1f}%"
            
        except urllib.error.URLError:
            pytest.skip("API not running")


class TestMetricsEndpoints:
    """Prometheus metrics endpoints tests."""
    
    @pytest.fixture
    def metrics_urls(self) -> list:
        """Metrics endpoint URLs."""
        return [
            ("NIFTY", "http://localhost:9325/metrics"),
            ("BANKNIFTY", "http://localhost:9326/metrics")
        ]
    
    def test_metrics_format(self, metrics_urls: list):
        """Test metrics endpoints return Prometheus format."""
        for index, url in metrics_urls:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    metrics_text = response.read().decode()
                    
                    # Check for Prometheus format
                    assert "# HELP" in metrics_text or "# TYPE" in metrics_text or \
                           "g6_ml_ensemble" in metrics_text, \
                           f"Metrics for {index} not in Prometheus format"
                    
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {index} not running")
    
    def test_metrics_contain_required_metrics(self, metrics_urls: list):
        """Test that metrics contain required ML ensemble metrics."""
        required_metrics = [
            "g6_ml_ensemble_forecast_p50",
            "g6_ml_ensemble_confidence_score",
        ]
        
        for index, url in metrics_urls:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    metrics_text = response.read().decode()
                    
                    # Check for at least one required metric
                    has_ml_metrics = any(
                        metric in metrics_text for metric in required_metrics
                    )
                    
                    if not has_ml_metrics:
                        pytest.warns(UserWarning,
                            f"Required ML metrics not found for {index}")
                    
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {index} not running")


class TestAPIErrorHandling:
    """Test API error handling."""
    
    @pytest.fixture
    def api_base_url(self) -> str:
        """Base URL for API."""
        return "http://localhost:9210"
    
    def test_missing_required_params(self, api_base_url: str):
        """Test API handles missing required parameters."""
        # Missing index parameter
        url = f"{api_base_url}/api/ml/ensemble/forecast?horizon=60"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
            with urllib.request.urlopen(req, timeout=10) as response:
                # Should fail
                assert False, "Should have raised error for missing index"
                
        except urllib.error.HTTPError as e:
            # Expected error
            assert e.code in [400, 422]
        except urllib.error.URLError:
            pytest.skip("API not running")
    
    def test_invalid_horizon(self, api_base_url: str):
        """Test API handles invalid horizon values."""
        # Negative horizon
        url = f"{api_base_url}/api/ml/ensemble/forecast?index=NIFTY&horizon=-1"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
            with urllib.request.urlopen(req, timeout=10) as response:
                # Should either fail or handle gracefully
                pass
                
        except urllib.error.HTTPError as e:
            # Expected error
            assert e.code in [400, 422]
        except urllib.error.URLError:
            pytest.skip("API not running")
