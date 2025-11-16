"""Test configuration validation functionality.

Tests for Phase 2.2b: Configuration Validation Layer
"""
import os
import pytest

from src.config.env_validator import G6ConfigValidator
from src.config.env_config import EnvConfig


def test_known_variable_validation(monkeypatch):
    """Test that known variables pass validation."""
    monkeypatch.setenv('G6_METRICS_ENABLED', '1')
    monkeypatch.setenv('G6_DEBUG', '0')
    
    warnings = G6ConfigValidator.validate_startup()
    # Should have no warnings for known variables
    assert len(warnings) == 0


def test_unknown_variable_detection(monkeypatch):
    """Test detection of unknown/typo variables."""
    # Intentional typo: COLLECTON instead of COLLECTION
    monkeypatch.setenv('G6_COLLECTON_INTERVAL', '60')
    
    warnings = G6ConfigValidator.validate_startup()
    assert len(warnings) == 1
    assert 'G6_COLLECTON_INTERVAL' in warnings[0]
    assert 'Unknown' in warnings[0]


def test_typo_suggestions(monkeypatch):
    """Test that similar variables are suggested for typos."""
    # Typo: METRCS instead of METRICS
    monkeypatch.setenv('G6_METRCS_ENABLED', '1')
    
    warnings = G6ConfigValidator.validate_startup()
    assert len(warnings) == 1
    # Should suggest G6_METRICS_ENABLED
    assert 'Did you mean' in warnings[0]


def test_deprecated_variable_warning(monkeypatch):
    """Test that deprecated variables generate warnings."""
    monkeypatch.setenv('G6_ENABLE_LEGACY_LOOP', '1')
    
    warnings = G6ConfigValidator.validate_startup()
    assert len(warnings) == 1
    assert 'Deprecated' in warnings[0]
    assert 'G6_ENABLE_LEGACY_LOOP' in warnings[0]


def test_strict_mode_fails_on_unknown(monkeypatch):
    """Test that strict mode raises error on unknown variables."""
    monkeypatch.setenv('G6_UNKNOWN_VAR_TEST', 'value')
    
    with pytest.raises(RuntimeError, match="Configuration validation failed"):
        G6ConfigValidator.validate_startup(strict=True)


def test_is_known_method():
    """Test is_known() method."""
    assert G6ConfigValidator.is_known('G6_METRICS_ENABLED')
    assert not G6ConfigValidator.is_known('G6_NONEXISTENT_VAR')


def test_is_deprecated_method():
    """Test is_deprecated() method."""
    assert G6ConfigValidator.is_deprecated('G6_ENABLE_LEGACY_LOOP')
    assert not G6ConfigValidator.is_deprecated('G6_METRICS_ENABLED')


def test_categorize_vars(monkeypatch):
    """Test variable categorization."""
    monkeypatch.setenv('G6_METRICS_ENABLED', '1')  # known
    monkeypatch.setenv('G6_UNKNOWN_TEST', '1')  # unknown
    monkeypatch.setenv('G6_ENABLE_LEGACY_LOOP', '1')  # deprecated
    
    categories = G6ConfigValidator.categorize_vars()
    
    assert 'G6_METRICS_ENABLED' in categories['known']
    assert 'G6_UNKNOWN_TEST' in categories['unknown']
    assert 'G6_ENABLE_LEGACY_LOOP' in categories['deprecated']


def test_envconfig_validate_known_integration(monkeypatch):
    """Test EnvConfig.validate_known() integration."""
    monkeypatch.setenv('G6_TYPO_VAR', 'test')
    
    warnings = EnvConfig.validate_known()
    assert len(warnings) == 1
    assert 'G6_TYPO_VAR' in warnings[0]


def test_multiple_unknown_variables(monkeypatch):
    """Test handling of multiple unknown variables."""
    monkeypatch.setenv('G6_UNKNOWN1', 'a')
    monkeypatch.setenv('G6_UNKNOWN2', 'b')
    monkeypatch.setenv('G6_UNKNOWN3', 'c')
    
    warnings = G6ConfigValidator.validate_startup()
    assert len(warnings) == 3


def test_get_all_g6_vars(monkeypatch):
    """Test getting all G6_ variables."""
    monkeypatch.setenv('G6_TEST1', 'val1')
    monkeypatch.setenv('G6_TEST2', 'val2')
    monkeypatch.setenv('OTHER_VAR', 'ignored')
    
    g6_vars = G6ConfigValidator.get_all_g6_vars()
    
    assert 'G6_TEST1' in g6_vars
    assert 'G6_TEST2' in g6_vars
    assert 'OTHER_VAR' not in g6_vars
