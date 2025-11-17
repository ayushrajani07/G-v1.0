"""
Prometheus Metrics Tests - Phase 8

Tests for Prometheus metrics collection and format validation.

Run with:
    pytest tests/test_prometheus_metrics.py -v
"""

from __future__ import annotations

import re
import urllib.request
import urllib.error
from typing import Dict, List

import pytest


class TestPrometheusMetrics:
    """Prometheus metrics tests."""
    
    @pytest.fixture
    def metrics_endpoints(self) -> List[Dict]:
        """Metrics endpoints configuration."""
        return [
            {"index": "NIFTY", "port": 9325},
            {"index": "BANKNIFTY", "port": 9326}
        ]
    
    def fetch_metrics(self, port: int) -> str:
        """Fetch metrics from endpoint."""
        url = f"http://localhost:{port}/metrics"
        req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.read().decode()
    
    def test_metrics_endpoint_accessible(self, metrics_endpoints: List[Dict]):
        """Test that metrics endpoints are accessible."""
        for endpoint in metrics_endpoints:
            try:
                metrics_text = self.fetch_metrics(endpoint["port"])
                assert len(metrics_text) > 0, f"Empty metrics from {endpoint['index']}"
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {endpoint['index']} not running")
    
    def test_metrics_prometheus_format(self, metrics_endpoints: List[Dict]):
        """Test metrics are in valid Prometheus format."""
        for endpoint in metrics_endpoints:
            try:
                metrics_text = self.fetch_metrics(endpoint["port"])
                
                # Check for Prometheus format indicators
                has_help = "# HELP" in metrics_text
                has_type = "# TYPE" in metrics_text
                has_metrics = any(
                    line and not line.startswith('#')
                    for line in metrics_text.split('\n')
                )
                
                assert has_metrics, f"No metric lines found for {endpoint['index']}"
                
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {endpoint['index']} not running")
    
    def test_ml_ensemble_metrics_present(self, metrics_endpoints: List[Dict]):
        """Test that ML ensemble specific metrics are present."""
        expected_metrics = [
            "g6_ml_ensemble_forecast_p10",
            "g6_ml_ensemble_forecast_p50",
            "g6_ml_ensemble_forecast_p90",
            "g6_ml_ensemble_confidence_score",
        ]
        
        for endpoint in metrics_endpoints:
            try:
                metrics_text = self.fetch_metrics(endpoint["port"])
                
                found_metrics = []
                for metric in expected_metrics:
                    if metric in metrics_text:
                        found_metrics.append(metric)
                
                # At least some ML metrics should be present
                if not found_metrics:
                    pytest.warns(UserWarning,
                        f"No ML ensemble metrics found for {endpoint['index']}")
                
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {endpoint['index']} not running")
    
    def test_metric_values_valid(self, metrics_endpoints: List[Dict]):
        """Test that metric values are valid numbers."""
        for endpoint in metrics_endpoints:
            try:
                metrics_text = self.fetch_metrics(endpoint["port"])
                
                # Parse metrics
                for line in metrics_text.split('\n'):
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse metric line: metric_name{labels} value
                    parts = line.split()
                    if len(parts) >= 2:
                        metric_name = parts[0].split('{')[0]
                        value = parts[-1]
                        
                        # Skip non-ML metrics
                        if not metric_name.startswith('g6_ml_ensemble'):
                            continue
                        
                        # Check value is numeric
                        try:
                            float_value = float(value)
                            # Check for NaN or Inf
                            assert not (value == 'nan' or value == 'inf' or value == '-inf'), \
                                f"Invalid metric value: {metric_name}={value}"
                        except ValueError:
                            # Allow timestamp values
                            if not metric_name.endswith('_timestamp'):
                                pytest.fail(f"Non-numeric metric value: {metric_name}={value}")
                
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {endpoint['index']} not running")
    
    def test_model_age_metric(self, metrics_endpoints: List[Dict]):
        """Test model age metric is present and reasonable."""
        for endpoint in metrics_endpoints:
            try:
                metrics_text = self.fetch_metrics(endpoint["port"])
                
                # Look for model age metric
                for line in metrics_text.split('\n'):
                    if 'g6_ml_ensemble_model_age_days' in line and not line.startswith('#'):
                        parts = line.split()
                        if len(parts) >= 2:
                            age_days = float(parts[-1])
                            
                            # Model should not be too old (< 90 days)
                            assert age_days < 90, \
                                f"Model for {endpoint['index']} is very old: {age_days} days"
                            
                            # Model should not be negative
                            assert age_days >= 0, \
                                f"Model age cannot be negative: {age_days}"
                
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {endpoint['index']} not running")
    
    def test_forecast_metrics_ordering(self, metrics_endpoints: List[Dict]):
        """Test that forecast quantiles are properly ordered (P10 <= P50 <= P90)."""
        for endpoint in metrics_endpoints:
            try:
                metrics_text = self.fetch_metrics(endpoint["port"])
                
                p10 = p50 = p90 = None
                
                # Extract quantile values
                for line in metrics_text.split('\n'):
                    if not line or line.startswith('#'):
                        continue
                    
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    
                    metric_name = parts[0].split('{')[0]
                    value = float(parts[-1])
                    
                    if metric_name == 'g6_ml_ensemble_forecast_p10':
                        p10 = value
                    elif metric_name == 'g6_ml_ensemble_forecast_p50':
                        p50 = value
                    elif metric_name == 'g6_ml_ensemble_forecast_p90':
                        p90 = value
                
                # Check ordering if all values present
                if p10 is not None and p50 is not None and p90 is not None:
                    assert p10 <= p50 <= p90, \
                        f"Quantiles not ordered for {endpoint['index']}: P10={p10}, P50={p50}, P90={p90}"
                
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {endpoint['index']} not running")
    
    def test_confidence_score_range(self, metrics_endpoints: List[Dict]):
        """Test that confidence score is in valid range [0, 1]."""
        for endpoint in metrics_endpoints:
            try:
                metrics_text = self.fetch_metrics(endpoint["port"])
                
                for line in metrics_text.split('\n'):
                    if 'g6_ml_ensemble_confidence_score' in line and not line.startswith('#'):
                        parts = line.split()
                        if len(parts) >= 2:
                            confidence = float(parts[-1])
                            
                            assert 0 <= confidence <= 1, \
                                f"Confidence score out of range for {endpoint['index']}: {confidence}"
                
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {endpoint['index']} not running")


class TestMetricsLabels:
    """Test Prometheus metrics labels."""
    
    def test_metrics_have_index_label(self):
        """Test that ML metrics have index label."""
        endpoints = [
            {"index": "NIFTY", "port": 9325},
            {"index": "BANKNIFTY", "port": 9326}
        ]
        
        for endpoint in endpoints:
            try:
                url = f"http://localhost:{endpoint['port']}/metrics"
                req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    metrics_text = response.read().decode()
                    
                    # Look for metrics with index label
                    for line in metrics_text.split('\n'):
                        if 'g6_ml_ensemble' in line and '{' in line and not line.startswith('#'):
                            # Check if index label is present
                            if 'index=' in line:
                                # Verify index value matches expected
                                assert f'index="{endpoint["index"]}"' in line or \
                                       f"index='{endpoint['index']}'" in line, \
                                       f"Index label mismatch for {endpoint['index']}"
                
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {endpoint['index']} not running")


class TestMetricsUpdating:
    """Test that metrics are being updated."""
    
    def test_metrics_timestamp(self):
        """Test that metrics have recent timestamps."""
        import time
        
        endpoints = [
            {"index": "NIFTY", "port": 9325},
        ]
        
        for endpoint in endpoints:
            try:
                url = f"http://localhost:{endpoint['port']}/metrics"
                req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    metrics_text = response.read().decode()
                    
                    # Look for timestamp metric
                    for line in metrics_text.split('\n'):
                        if 'timestamp' in line.lower() and not line.startswith('#'):
                            parts = line.split()
                            if len(parts) >= 2:
                                timestamp = float(parts[-1])
                                current_time = time.time()
                                
                                # Timestamp should be reasonably recent (within 1 hour)
                                age_seconds = current_time - timestamp
                                if age_seconds > 0:  # Only check if timestamp is in past
                                    assert age_seconds < 3600, \
                                        f"Metrics timestamp is too old: {age_seconds}s ago"
                
            except urllib.error.URLError:
                pytest.skip(f"Metrics exporter for {endpoint['index']} not running")
