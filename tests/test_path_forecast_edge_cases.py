"""Edge case tests for path_forecast module.

Tests for error handling, boundary conditions, and fallback behaviors
added as part of Phase 6 cleanup.
"""
import pytest
from src.path_forecast.common import extract_tp, safe_int, safe_float, clamp
from src.path_forecast.params import (
    sanitize_window,
    sanitize_horizon,
    sanitize_k,
    clamp_alpha,
    DEFAULT_ALPHA_MIN,
    DEFAULT_ALPHA_MAX,
)


class TestCommonSafeIntFloat:
    """Test safe_int and safe_float error handling."""

    def test_safe_int_valid_inputs(self):
        assert safe_int(42) == 42
        assert safe_int("42") == 42
        assert safe_int(42.7) == 42
        assert safe_int("42.7") == 42

    def test_safe_int_invalid_inputs(self):
        assert safe_int("invalid", default=99) == 99
        assert safe_int(None, default=10) == 10
        assert safe_int("", default=5) == 5

    def test_safe_int_with_bounds(self):
        assert safe_int(100, default=50, min_=0, max_=50) == 50
        assert safe_int(-10, default=50, min_=0, max_=100) == 0
        assert safe_int(25, default=50, min_=0, max_=100) == 25

    def test_safe_float_valid_inputs(self):
        assert safe_float(3.14) == 3.14
        assert safe_float("3.14") == 3.14
        assert safe_float(42) == 42.0

    def test_safe_float_invalid_inputs(self):
        assert safe_float("invalid", default=1.5) == 1.5
        assert safe_float(None, default=2.5) == 2.5
        assert safe_float("", default=0.0) == 0.0

    def test_safe_float_with_bounds(self):
        assert safe_float(100.0, default=50.0, min_=0.0, max_=50.0) == 50.0
        assert safe_float(-10.0, default=50.0, min_=0.0, max_=100.0) == 0.0
        assert safe_float(25.5, default=50.0, min_=0.0, max_=100.0) == 25.5

    def test_clamp_function(self):
        assert clamp(5.0, 0.0, 10.0) == 5.0
        assert clamp(-5.0, 0.0, 10.0) == 0.0
        assert clamp(15.0, 0.0, 10.0) == 10.0
        # Test with invalid input (should use lower bound)
        assert clamp("invalid", 1.0, 10.0) == 1.0


class TestExtractTPEdgeCases:
    """Additional edge cases for extract_tp."""

    def test_extract_tp_with_empty_strings(self):
        assert extract_tp({"tp": ""}) is None
        assert extract_tp({"tp": None}) is None

    def test_extract_tp_with_zero(self):
        assert extract_tp({"tp": 0}) == 0.0
        assert extract_tp({"tp": 0.0}) == 0.0

    def test_extract_tp_ce_pe_with_zero(self):
        assert extract_tp({"ce": 0, "pe": 100}) == 100.0
        assert extract_tp({"ce": 50, "pe": 0}) == 50.0
        assert extract_tp({"ce": 0, "pe": 0}) == 0.0

    def test_extract_tp_mixed_types(self):
        # Test string representations
        assert extract_tp({"tp": "123.45"}) == 123.45
        assert extract_tp({"ce": "50.5", "pe": "49.5"}) == 100.0

    def test_extract_tp_large_values(self):
        assert extract_tp({"tp": 999999.99}) == 999999.99
        assert extract_tp({"ce": 500000, "pe": 500000}) == 1000000.0


class TestParamsSanitization:
    """Test parameter sanitization functions."""

    def test_sanitize_window_valid_range(self):
        assert sanitize_window(60) == 60
        assert sanitize_window("120") == 120
        assert sanitize_window(1) == 1
        assert sanitize_window(720) == 720

    def test_sanitize_window_out_of_bounds(self):
        # Should clamp to bounds
        assert sanitize_window(0) == 1  # Below min
        assert sanitize_window(1000) == 720  # Above max
        assert sanitize_window(-10) == 1  # Negative

    def test_sanitize_window_invalid(self):
        # Should return default (60)
        assert sanitize_window("invalid") == 60
        assert sanitize_window(None) == 60

    def test_sanitize_horizon_boundaries(self):
        assert sanitize_horizon(1) == 1
        assert sanitize_horizon(720) == 720
        assert sanitize_horizon(0) == 1
        assert sanitize_horizon(1000) == 720

    def test_sanitize_k_boundaries(self):
        assert sanitize_k(15) == 15
        assert sanitize_k(1) == 1
        assert sanitize_k(1000) == 1000
        assert sanitize_k(0) == 1
        assert sanitize_k(2000) == 1000

    def test_clamp_alpha_uses_constants(self):
        # Test that clamp_alpha uses centralized constants
        assert clamp_alpha(0.5) == 0.5
        assert clamp_alpha(0.2) == DEFAULT_ALPHA_MIN
        assert clamp_alpha(1.0) == DEFAULT_ALPHA_MAX
        assert clamp_alpha(DEFAULT_ALPHA_MIN) == DEFAULT_ALPHA_MIN
        assert clamp_alpha(DEFAULT_ALPHA_MAX) == DEFAULT_ALPHA_MAX


class TestRetrievalEdgeCases:
    """Edge cases for retrieval forecaster."""

    def test_no_historical_candidates(self):
        """Test behavior when no historical data is available."""
        from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RetrievalConfig(
                root=Path(tmpdir),
                expiry_tag="weekly",
                offset="ATM+0",
            )
            forecaster = RetrievalPathForecaster(cfg)

            # Empty recent window should raise ValueError
            recent_window = []
            context = {
                "index": "NIFTY",
                "now_ms": 1700000000000,
                "live_rows": [],
            }

            # Should raise ValueError for insufficient data
            with pytest.raises(ValueError, match="insufficient rows"):
                forecaster.forecast_path(
                    recent_window,
                    context=context,
                    quantiles=[0.1, 0.5, 0.9],
                    horizon_minutes=60,
                )


class TestCompositeEdgeCases:
    """Edge cases for composite forecaster."""

    def test_extreme_alpha_values(self):
        """Test that alpha clamping works correctly."""
        from src.path_forecast.params import clamp_alpha

        # Test boundary values
        assert 0.3 <= clamp_alpha(-10.0) <= 0.9
        assert 0.3 <= clamp_alpha(0.0) <= 0.9
        assert 0.3 <= clamp_alpha(100.0) <= 0.9
        assert clamp_alpha(0.5) == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
