"""Unit tests for Phase 9 weighted quantile simplification and monotonicity."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# Import the internal quantile functions for testing
from src.path_forecast.retrieval import _quantile, _weighted_quantile


class TestUnweightedQuantile:
    """Test unweighted quantile function."""
    
    def test_single_value(self):
        """Test quantile of single value."""
        assert _quantile([5.0], 0.5) == 5.0
        assert _quantile([5.0], 0.0) == 5.0
        assert _quantile([5.0], 1.0) == 5.0
    
    def test_two_values(self):
        """Test quantile of two values."""
        values = [1.0, 3.0]
        assert _quantile(values, 0.0) == 1.0
        assert _quantile(values, 1.0) == 3.0
        q50 = _quantile(values, 0.5)
        assert 1.0 <= q50 <= 3.0  # Should be between min and max
    
    def test_sorted_values(self):
        """Test with already sorted values."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _quantile(values, 0.0) <= _quantile(values, 0.25)
        assert _quantile(values, 0.25) <= _quantile(values, 0.5)
        assert _quantile(values, 0.5) <= _quantile(values, 0.75)
        assert _quantile(values, 0.75) <= _quantile(values, 1.0)
    
    def test_unsorted_values(self):
        """Test with unsorted values."""
        values = [5.0, 1.0, 3.0, 4.0, 2.0]
        assert _quantile(values, 0.0) == 1.0
        assert _quantile(values, 1.0) == 5.0
        q50 = _quantile(values, 0.5)
        assert 2.0 <= q50 <= 4.0
    
    def test_monotonicity(self):
        """Test that quantiles are monotonic."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        quantiles = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        
        results = [_quantile(values, q) for q in quantiles]
        
        # Check monotonicity: each quantile >= previous
        for i in range(1, len(results)):
            assert results[i] >= results[i-1], f"Monotonicity violation at q={quantiles[i]}"
    
    def test_empty_list(self):
        """Test empty list returns NaN."""
        result = _quantile([], 0.5)
        assert result != result  # NaN != NaN


class TestWeightedQuantile:
    """Test weighted quantile function."""
    
    def test_equal_weights(self):
        """Test that equal weights match unweighted quantile."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        weights = [1.0, 1.0, 1.0, 1.0, 1.0]
        
        for q in [0.0, 0.25, 0.5, 0.75, 1.0]:
            weighted = _weighted_quantile(values, weights, q)
            unweighted = _quantile(values, q)
            # Should be close (may not be exact due to different interpolation)
            assert abs(weighted - unweighted) < 0.5
    
    def test_single_nonzero_weight(self):
        """Test that single nonzero weight returns that value."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        weights = [0.0, 0.0, 1.0, 0.0, 0.0]
        
        # All quantiles should return the value with nonzero weight
        for q in [0.0, 0.5, 1.0]:
            result = _weighted_quantile(values, weights, q)
            assert result == 3.0
    
    def test_zero_weights_fallback(self):
        """Test that all zero weights fall back to unweighted."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        weights = [0.0, 0.0, 0.0, 0.0, 0.0]
        
        weighted = _weighted_quantile(values, weights, 0.5)
        unweighted = _quantile(values, 0.5)
        
        # Should fall back to unweighted quantile
        assert abs(weighted - unweighted) < 0.5
    
    def test_weighted_monotonicity(self):
        """Test that weighted quantiles are monotonic."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        weights = [1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 2.0, 2.0, 1.0, 1.0]
        quantiles = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        
        results = [_weighted_quantile(values, weights, q) for q in quantiles]
        
        # Check monotonicity: each quantile >= previous
        for i in range(1, len(results)):
            assert results[i] >= results[i-1], f"Monotonicity violation at q={quantiles[i]}"
    
    def test_inverse_distance_weights(self):
        """Test with inverse distance weights (typical use case)."""
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        distances = [0.1, 0.2, 0.3, 0.4, 0.5]
        weights = [1.0 / (1e-6 + d) for d in distances]
        
        # Normalize weights
        total = sum(weights)
        weights = [w / total for w in weights]
        
        result = _weighted_quantile(values, weights, 0.5)
        
        # Should be biased toward lower values (lower distance = higher weight)
        assert 10.0 <= result <= 50.0
    
    def test_negative_weights_clamped(self):
        """Test that negative weights are treated as zero."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        weights = [-1.0, 0.0, 1.0, 0.0, 0.0]  # Negative weight should be clamped
        
        result = _weighted_quantile(values, weights, 0.5)
        
        # Should only consider value with weight 1.0
        assert result == 3.0
    
    def test_boundary_quantiles(self):
        """Test boundary quantiles (0.0 and 1.0)."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        weights = [2.0, 1.0, 1.0, 1.0, 2.0]
        
        q0 = _weighted_quantile(values, weights, 0.0)
        q100 = _weighted_quantile(values, weights, 1.0)
        
        # Q0 should be min, Q100 should be max
        assert q0 == min(values)
        assert q100 == max(values)


class TestWeightedQuantileToggle:
    """Test PATH_FORECAST_DISABLE_WEIGHTED flag behavior."""
    
    @patch.dict(os.environ, {"PATH_FORECAST_DISABLE_WEIGHTED": "1"})
    def test_flag_disables_weighted(self):
        """Test that setting the flag would disable weighted quantiles."""
        # This test verifies the flag exists and can be read
        import os
        from src.path_forecast.common import env_flag as _env_flag
        
        # The flag should be readable
        disabled = _env_flag('PATH_FORECAST_DISABLE_WEIGHTED')
        assert disabled is True
    
    @patch.dict(os.environ, {}, clear=True)
    def test_flag_default_false(self):
        """Test that flag is false by default."""
        from src.path_forecast.common import env_flag as _env_flag
        
        disabled = _env_flag('PATH_FORECAST_DISABLE_WEIGHTED')
        assert disabled is False


class TestMonotonicityInvariance:
    """Test that monotonicity is preserved under various conditions."""
    
    def test_many_values_unweighted(self):
        """Test monotonicity with many values (unweighted)."""
        import random
        
        # Generate random values
        random.seed(42)
        values = [random.uniform(0, 100) for _ in range(100)]
        
        # Test monotonicity across many quantiles
        quantiles = [i / 100.0 for i in range(101)]
        results = [_quantile(values, q) for q in quantiles]
        
        # Verify monotonicity
        for i in range(1, len(results)):
            assert results[i] >= results[i-1] - 1e-10, f"Monotonicity violated at q={quantiles[i]}"
    
    def test_many_values_weighted(self):
        """Test monotonicity with many values (weighted)."""
        import random
        
        random.seed(42)
        values = [random.uniform(0, 100) for _ in range(100)]
        weights = [random.uniform(0.1, 2.0) for _ in range(100)]
        
        # Normalize weights
        total = sum(weights)
        weights = [w / total for w in weights]
        
        # Test monotonicity across many quantiles
        quantiles = [i / 100.0 for i in range(101)]
        results = [_weighted_quantile(values, weights, q) for q in quantiles]
        
        # Verify monotonicity
        for i in range(1, len(results)):
            assert results[i] >= results[i-1] - 1e-10, f"Monotonicity violated at q={quantiles[i]}"
    
    def test_coverage_invariance(self):
        """Test that weighted vs unweighted coverage is similar."""
        import random
        
        random.seed(42)
        values = [random.uniform(0, 100) for _ in range(50)]
        weights_equal = [1.0] * len(values)
        weights_varied = [random.uniform(0.5, 1.5) for _ in range(len(values))]
        
        # Normalize varied weights
        total = sum(weights_varied)
        weights_varied = [w / total for w in weights_varied]
        
        # Compare 10th and 90th percentiles
        q10_unweighted = _quantile(values, 0.1)
        q90_unweighted = _quantile(values, 0.9)
        
        q10_equal = _weighted_quantile(values, weights_equal, 0.1)
        q90_equal = _weighted_quantile(values, weights_equal, 0.9)
        
        q10_varied = _weighted_quantile(values, weights_varied, 0.1)
        q90_varied = _weighted_quantile(values, weights_varied, 0.9)
        
        # Equal weights should be close to unweighted
        assert abs(q10_equal - q10_unweighted) < 5.0
        assert abs(q90_equal - q90_unweighted) < 5.0
        
        # Varied weights should still be in reasonable range
        assert min(values) <= q10_varied <= max(values)
        assert min(values) <= q90_varied <= max(values)
        assert q10_varied <= q90_varied  # Monotonicity


def test_real_world_scenario():
    """Test with realistic trading data scenario."""
    # Simulated TP values from different historical days
    day1 = [100.0, 102.0, 101.0, 103.0, 105.0]
    day2 = [98.0, 100.0, 99.0, 101.0, 103.0]
    day3 = [105.0, 107.0, 106.0, 108.0, 110.0]
    day4 = [97.0, 99.0, 98.0, 100.0, 102.0]
    day5 = [103.0, 105.0, 104.0, 106.0, 108.0]
    
    # For each time step, aggregate across days
    for i in range(5):
        values = [day1[i], day2[i], day3[i], day4[i], day5[i]]
        
        # Unweighted quantiles
        q10 = _quantile(values, 0.1)
        q50 = _quantile(values, 0.5)
        q90 = _quantile(values, 0.9)
        
        # Should be monotonic
        assert q10 <= q50 <= q90
        
        # Weighted with inverse distances
        distances = [0.5, 1.0, 0.3, 1.5, 0.8]
        weights = [1.0 / (1e-6 + d) for d in distances]
        total = sum(weights)
        weights = [w / total for w in weights]
        
        q10_w = _weighted_quantile(values, weights, 0.1)
        q50_w = _weighted_quantile(values, weights, 0.5)
        q90_w = _weighted_quantile(values, weights, 0.9)
        
        # Should be monotonic
        assert q10_w <= q50_w <= q90_w
        
        # Should be in reasonable range
        assert min(values) <= q10_w <= max(values)
        assert min(values) <= q50_w <= max(values)
        assert min(values) <= q90_w <= max(values)
