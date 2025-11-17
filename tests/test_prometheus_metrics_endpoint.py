"""Tests for Prometheus metrics exposure endpoint.

Validates that:
1. /metrics endpoint returns 404 when ENABLE_PATH_FORECAST_PROM_METRICS is not set
2. /metrics endpoint returns metrics when ENABLE_PATH_FORECAST_PROM_METRICS=1
3. All required metrics are present in the output
4. Metrics format is valid Prometheus exposition format
"""
import os
import pytest
from fastapi.testclient import TestClient


def test_metrics_endpoint_disabled():
    """Test that /metrics returns 404 when not enabled."""
    # Ensure flag is not set
    os.environ.pop("ENABLE_PATH_FORECAST_PROM_METRICS", None)
    
    # Import app after clearing environment variable
    from src.web.dashboard.app import app
    client = TestClient(app)
    
    response = client.get("/metrics")
    assert response.status_code == 404
    assert "not enabled" in response.text.lower()


def test_metrics_endpoint_enabled():
    """Test that /metrics returns valid metrics when enabled."""
    # Set the enable flag
    os.environ["ENABLE_PATH_FORECAST_PROM_METRICS"] = "1"
    
    try:
        # Import app after setting environment variable
        # Need to reload modules to pick up new env var
        import importlib
        import sys
        
        # Remove cached modules to force reload
        modules_to_reload = [
            'src.web.dashboard.prom_metrics',
            'src.web.dashboard.app',
        ]
        for mod in modules_to_reload:
            if mod in sys.modules:
                del sys.modules[mod]
        
        from src.web.dashboard.app import app
        client = TestClient(app)
        
        response = client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        
        # Parse metrics output
        metrics_text = response.text
        
        # Check that required metrics are present
        required_metrics = [
            "g6_forecast_latency_ms",
            "g6_forecast_cache_hits_total",
            "g6_forecast_cache_misses_total",
            "g6_recent_window_cache_hits_total",
            "g6_recent_window_cache_misses_total",
            "g6_forecast_cache_size",
            "g6_recent_window_cache_size",
        ]
        
        for metric_name in required_metrics:
            assert metric_name in metrics_text, f"Metric {metric_name} not found in output"
        
        # Verify it's valid Prometheus format (has TYPE and HELP comments)
        assert "# HELP" in metrics_text
        assert "# TYPE" in metrics_text
        
    finally:
        # Clean up environment variable
        os.environ.pop("ENABLE_PATH_FORECAST_PROM_METRICS", None)


def test_metrics_module_functionality():
    """Test prom_metrics module functions directly."""
    os.environ["ENABLE_PATH_FORECAST_PROM_METRICS"] = "1"
    
    try:
        # Import after setting env var
        import importlib
        import sys
        
        # Remove cached module to force reload
        if 'src.web.dashboard.prom_metrics' in sys.modules:
            del sys.modules['src.web.dashboard.prom_metrics']
        
        from src.web.dashboard.prom_metrics import (
            observe_forecast_latency,
            increment_forecast_cache_hit,
            increment_forecast_cache_miss,
            increment_recent_window_cache_hit,
            increment_recent_window_cache_miss,
            set_forecast_cache_size,
            set_recent_window_cache_size,
            get_registry,
        )
        
        # Test that functions don't raise exceptions
        observe_forecast_latency("NIFTY", 60, 123.45)
        increment_forecast_cache_hit("NIFTY")
        increment_forecast_cache_miss("NIFTY")
        increment_recent_window_cache_hit("NIFTY")
        increment_recent_window_cache_miss("NIFTY")
        set_forecast_cache_size(10)
        set_recent_window_cache_size(5)
        
        # Verify registry is available
        registry = get_registry()
        assert registry is not None
        
        # Generate metrics output
        from prometheus_client import generate_latest
        metrics_output = generate_latest(registry)
        assert len(metrics_output) > 0
        assert b"g6_forecast_latency_ms" in metrics_output
        
    finally:
        os.environ.pop("ENABLE_PATH_FORECAST_PROM_METRICS", None)


def test_metrics_disabled_functions_are_noop():
    """Test that metric functions are no-op when disabled."""
    # Ensure flag is not set
    os.environ.pop("ENABLE_PATH_FORECAST_PROM_METRICS", None)
    
    # Import after clearing env var
    import importlib
    import sys
    
    # Remove cached module to force reload
    if 'src.web.dashboard.prom_metrics' in sys.modules:
        del sys.modules['src.web.dashboard.prom_metrics']
    
    from src.web.dashboard.prom_metrics import (
        observe_forecast_latency,
        increment_forecast_cache_hit,
        get_registry,
    )
    
    # These should not raise exceptions even when disabled
    observe_forecast_latency("NIFTY", 60, 123.45)
    increment_forecast_cache_hit("NIFTY")
    
    # Registry should be None when disabled
    registry = get_registry()
    assert registry is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
