"""Test performance alert metrics for Phase 10.

Validates that required metrics for performance alert rules are properly exported:
- g6_forecast_cache_evictions_total (counter with index label)
- g6_forecast_cache_dynamic_ttl (gauge with index label)
"""
import os
import pytest


def test_eviction_counter_exists_when_enabled():
    """Verify eviction counter is exported when metrics enabled."""
    os.environ['ENABLE_PATH_FORECAST_PROM_METRICS'] = '1'
    
    # Import after setting env var to trigger initialization
    from src.web.dashboard import prom_metrics
    
    # Force metrics initialization
    registry = prom_metrics.get_registry()
    
    if registry is None:
        pytest.skip("Prometheus client not installed")
    
    # Collect all metric families
    metric_names = set()
    for family in registry.collect():
        name = getattr(family, 'name', None)
        if name:
            metric_names.add(name)
    
    # Verify eviction counter is present (prometheus_client may or may not add _total suffix)
    has_eviction_metric = (
        'g6_forecast_cache_evictions_total' in metric_names or
        'g6_forecast_cache_evictions' in metric_names
    )
    assert has_eviction_metric, \
        f"g6_forecast_cache_evictions metric not found in registry. Available: {metric_names}"


def test_dynamic_ttl_gauge_exists_when_enabled():
    """Verify dynamic TTL gauge is exported when metrics enabled."""
    os.environ['ENABLE_PATH_FORECAST_PROM_METRICS'] = '1'
    
    from src.web.dashboard import prom_metrics
    
    registry = prom_metrics.get_registry()
    
    if registry is None:
        pytest.skip("Prometheus client not installed")
    
    metric_names = set()
    for family in registry.collect():
        name = getattr(family, 'name', None)
        if name:
            metric_names.add(name)
    
    # Verify dynamic TTL gauge is present
    assert 'g6_forecast_cache_dynamic_ttl' in metric_names, \
        "g6_forecast_cache_dynamic_ttl metric not found in registry"


def test_eviction_counter_increments():
    """Verify eviction counter increments correctly."""
    os.environ['ENABLE_PATH_FORECAST_PROM_METRICS'] = '1'
    
    from src.web.dashboard import prom_metrics
    
    registry = prom_metrics.get_registry()
    
    if registry is None:
        pytest.skip("Prometheus client not installed")
    
    # Increment eviction counter for test index
    test_index = "NIFTY"
    prom_metrics.increment_forecast_cache_eviction(test_index)
    
    # Collect metrics and verify counter increased
    found_metric = False
    for family in registry.collect():
        name = getattr(family, 'name', None)
        # Check both with and without _total suffix
        if name in ('g6_forecast_cache_evictions_total', 'g6_forecast_cache_evictions'):
            for sample in family.samples:
                if sample.labels.get('index') == test_index:
                    # Value should be at least 1 (we just incremented)
                    assert sample.value >= 1, \
                        f"Eviction counter should be >= 1, got {sample.value}"
                    found_metric = True
                    break
    
    assert found_metric, \
        f"Could not find eviction counter metric for index {test_index}"


def test_dynamic_ttl_gauge_sets_value():
    """Verify dynamic TTL gauge can be set."""
    os.environ['ENABLE_PATH_FORECAST_PROM_METRICS'] = '1'
    
    from src.web.dashboard import prom_metrics
    
    registry = prom_metrics.get_registry()
    
    if registry is None:
        pytest.skip("Prometheus client not installed")
    
    # Set TTL gauge for test index
    test_index = "BANKNIFTY"
    test_ttl = 42.5
    prom_metrics.set_forecast_cache_dynamic_ttl(test_index, test_ttl)
    
    # Collect metrics and verify gauge value
    found_metric = False
    for family in registry.collect():
        name = getattr(family, 'name', None)
        if name == 'g6_forecast_cache_dynamic_ttl':
            for sample in family.samples:
                if sample.labels.get('index') == test_index:
                    # Value should match what we set
                    assert abs(sample.value - test_ttl) < 0.01, \
                        f"TTL gauge should be {test_ttl}, got {sample.value}"
                    found_metric = True
                    break
    
    assert found_metric, \
        f"Could not find dynamic TTL gauge metric for index {test_index}"


def test_metrics_not_exported_when_disabled():
    """Verify metrics not exported when ENABLE_PATH_FORECAST_PROM_METRICS not set."""
    # Ensure env var is not set
    os.environ.pop('ENABLE_PATH_FORECAST_PROM_METRICS', None)
    
    from src.web.dashboard import prom_metrics
    
    registry = prom_metrics.get_registry()
    
    # Registry should be None when disabled
    assert registry is None, \
        "Registry should be None when ENABLE_PATH_FORECAST_PROM_METRICS not set"


def test_all_required_performance_metrics_present():
    """Comprehensive check that all metrics needed for performance alerts exist."""
    os.environ['ENABLE_PATH_FORECAST_PROM_METRICS'] = '1'
    
    from src.web.dashboard import prom_metrics
    
    registry = prom_metrics.get_registry()
    
    if registry is None:
        pytest.skip("Prometheus client not installed")
    
    # Required metrics for performance alert rules (flexible with/without _total suffix)
    required_base_metrics = {
        'g6_forecast_latency_ms',  # histogram for P95 latency alert
        'g6_forecast_coverage_pct',  # gauge for low coverage alert
        'g6_forecast_norm_error_hist',  # histogram for high norm error tail alert
        'g6_forecast_cache_dynamic_ttl',  # gauge for adaptive TTL alerts
        'g6_forecast_mae',  # gauge for MAE spike alert
    }
    
    # Collect all metric families
    metric_names = set()
    for family in registry.collect():
        name = getattr(family, 'name', None)
        if name:
            metric_names.add(name)
    
    # Verify all required metrics are present
    missing = required_base_metrics - metric_names
    assert not missing, \
        f"Missing required performance metrics: {missing}"
    
    # Check eviction counter (may have _total suffix or not)
    has_eviction = (
        'g6_forecast_cache_evictions_total' in metric_names or
        'g6_forecast_cache_evictions' in metric_names
    )
    assert has_eviction, \
        "Missing eviction counter metric (g6_forecast_cache_evictions)"
