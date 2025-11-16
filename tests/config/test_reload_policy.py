"""Tests for reload policy functionality.

Tests for Phase 2.2c: Hot-Reload Controls
"""
import pytest

from src.config.reload_policy import ReloadPolicy, ReloadBehavior


def test_startup_only_variables():
    """Test identification of startup-only variables."""
    assert ReloadPolicy.is_startup_only('G6_METRICS_PORT')
    assert ReloadPolicy.is_startup_only('G6_CSV_BASE_DIR')
    assert ReloadPolicy.is_startup_only('G6_LOG_LEVEL')
    assert not ReloadPolicy.is_startup_only('G6_METRICS_ENABLED')


def test_hot_reload_variables():
    """Test identification of hot-reload variables."""
    assert ReloadPolicy.is_hot_reload('G6_ADAPTIVE_CONTROLLER')
    assert ReloadPolicy.is_hot_reload('G6_ADAPTIVE_MIN_DETAIL_MODE')
    assert ReloadPolicy.is_hot_reload('G6_MEMORY_TIER')
    assert not ReloadPolicy.is_hot_reload('G6_METRICS_PORT')


def test_runtime_variables():
    """Test identification of runtime variables."""
    assert ReloadPolicy.is_runtime('G6_METRICS_ENABLED')
    assert ReloadPolicy.is_runtime('G6_ENABLE_DATA_QUALITY')
    assert not ReloadPolicy.is_runtime('G6_METRICS_PORT')
    assert not ReloadPolicy.is_runtime('G6_ADAPTIVE_CONTROLLER')


def test_get_reload_behavior():
    """Test getting reload behavior enum."""
    assert ReloadPolicy.get_reload_behavior('G6_METRICS_PORT') == ReloadBehavior.STARTUP_ONLY
    assert ReloadPolicy.get_reload_behavior('G6_ADAPTIVE_CONTROLLER') == ReloadBehavior.HOT_RELOAD
    assert ReloadPolicy.get_reload_behavior('G6_METRICS_ENABLED') == ReloadBehavior.RUNTIME


def test_get_reload_endpoint():
    """Test getting hot-reload endpoint."""
    endpoint = ReloadPolicy.get_reload_endpoint('G6_ADAPTIVE_CONTROLLER')
    assert endpoint == '/adaptive/theme'
    
    endpoint = ReloadPolicy.get_reload_endpoint('G6_MEMORY_TIER')
    assert endpoint == '/adaptive/theme'
    
    endpoint = ReloadPolicy.get_reload_endpoint('G6_METRICS_PORT')
    assert endpoint is None


def test_warn_if_startup_only_no_change():
    """Test no warning when startup-only variable doesn't change."""
    warned = ReloadPolicy.warn_if_startup_only('G6_METRICS_PORT', '9108', '9108')
    assert not warned


def test_warn_if_startup_only_first_set():
    """Test no warning when setting startup-only variable for first time."""
    warned = ReloadPolicy.warn_if_startup_only('G6_METRICS_PORT', None, '9108')
    assert not warned


def test_warn_if_startup_only_changed(caplog):
    """Test warning when changing startup-only variable at runtime."""
    import logging
    caplog.set_level(logging.WARNING)
    
    warned = ReloadPolicy.warn_if_startup_only('G6_METRICS_PORT', '9108', '9109')
    assert warned
    assert any('requires restart' in record.message.lower() for record in caplog.records)


def test_warn_if_startup_only_runtime_var():
    """Test no warning for runtime variables."""
    warned = ReloadPolicy.warn_if_startup_only('G6_METRICS_ENABLED', '1', '0')
    assert not warned


def test_categorize_all(monkeypatch):
    """Test categorization of all variables."""
    monkeypatch.setenv('G6_METRICS_PORT', '9108')  # startup-only
    monkeypatch.setenv('G6_ADAPTIVE_CONTROLLER', '1')  # hot-reload
    monkeypatch.setenv('G6_METRICS_ENABLED', '1')  # runtime
    
    categories = ReloadPolicy.categorize_all()
    
    assert 'G6_METRICS_PORT' in categories['startup_only']
    assert 'G6_ADAPTIVE_CONTROLLER' in categories['hot_reload']
    assert 'G6_METRICS_ENABLED' in categories['runtime']


def test_document_variable_startup_only():
    """Test documentation for startup-only variable."""
    doc = ReloadPolicy.document_variable('G6_METRICS_PORT')
    assert doc['behavior'] == 'startup-only'
    assert 'restart' in doc['description'].lower()
    assert 'endpoint' not in doc


def test_document_variable_hot_reload():
    """Test documentation for hot-reload variable."""
    doc = ReloadPolicy.document_variable('G6_ADAPTIVE_CONTROLLER')
    assert doc['behavior'] == 'hot-reload'
    assert 'immediate' in doc['description'].lower()
    assert doc['endpoint'] == '/adaptive/theme'


def test_document_variable_runtime():
    """Test documentation for runtime variable."""
    doc = ReloadPolicy.document_variable('G6_METRICS_ENABLED')
    assert doc['behavior'] == 'runtime'
    assert 'next' in doc['description'].lower() and 'cycle' in doc['description'].lower()
    assert 'endpoint' not in doc
