"""
Tests for ensemble path forecaster.

Tests the integration of baseline, GBRT, and retrieval forecasters
with confidence-based adaptive weighting.
"""

import pytest
from pathlib import Path
from typing import List

from src.path_forecast.ensemble import EnsembleForecaster, EnsembleConfig


class TestEnsembleConfig:
    """Test EnsembleConfig dataclass."""
    
    def test_default_config(self):
        """Test default configuration values."""
        cfg = EnsembleConfig()
        
        assert cfg.baseline_enabled is True
        assert cfg.gbrt_enabled is True
        assert cfg.retrieval_enabled is True
        assert cfg.conformal_enabled is True
        
        assert cfg.baseline_k == 1.0
        assert cfg.weighting_strategy == "confidence_adaptive"
        assert cfg.confidence_threshold == 0.7
    
    def test_custom_config(self):
        """Test custom configuration values."""
        cfg = EnsembleConfig(
            baseline_k=1.5,
            weights_high_conf_gbrt=0.9,
            weights_high_conf_retrieval=0.1,
            confidence_threshold=0.8,
        )
        
        assert cfg.baseline_k == 1.5
        assert cfg.weights_high_conf_gbrt == 0.9
        assert cfg.weights_high_conf_retrieval == 0.1
        assert cfg.confidence_threshold == 0.8


class TestEnsembleForecaster:
    """Test EnsembleForecaster class."""
    
    @pytest.fixture
    def minimal_config(self):
        """Create minimal config for testing."""
        return EnsembleConfig(
            baseline_enabled=True,
            gbrt_enabled=False,  # Disable GBRT for basic tests
            retrieval_enabled=False,  # Disable retrieval for basic tests
            conformal_enabled=False,
        )
    
    @pytest.fixture
    def forecaster(self, minimal_config):
        """Create forecaster instance."""
        return EnsembleForecaster(minimal_config)
    
    def test_initialization(self, forecaster):
        """Test forecaster initialization."""
        assert forecaster is not None
        assert forecaster.cfg is not None
        assert isinstance(forecaster.last_meta, dict)
    
    def test_baseline_only_forecast(self, forecaster):
        """Test forecast with only baseline enabled."""
        # Prepare input
        recent_window = [[100.0] for _ in range(60)]
        context = {
            "index": "NIFTY",
            "now_ms": 1700000000000,
            "underlying": 19500.0,
            "avg_iv": 0.15,
            "minutes_to_expiry": 300.0,
        }
        
        # Generate forecast
        times, quantiles = forecaster.forecast_path(
            recent_window,
            context=context,
            quantiles=[0.1, 0.5, 0.9],
            horizon_minutes=60,
            bucket_ms=60000,
        )
        
        # Verify output structure
        assert len(times) == 60
        assert 0.1 in quantiles
        assert 0.5 in quantiles
        assert 0.9 in quantiles
        assert len(quantiles[0.5]) == 60
        
        # Verify metadata
        assert "baseline_tp" in forecaster.last_meta
        assert forecaster.last_meta["baseline_enabled"] is True
    
    def test_compute_baseline(self, forecaster):
        """Test baseline computation."""
        baseline = forecaster._compute_baseline(
            underlying=19500.0,
            avg_iv=0.15,
            minutes_to_expiry=300.0,
        )
        
        assert baseline > 0
        assert isinstance(baseline, float)
    
    def test_confidence_computation(self, forecaster):
        """Test confidence score computation."""
        # Test with different candidate counts
        forecaster.last_meta["retrieval_candidates"] = 0
        conf0 = forecaster._compute_confidence({})
        
        forecaster.last_meta["retrieval_candidates"] = 5
        conf5 = forecaster._compute_confidence({})
        
        forecaster.last_meta["retrieval_candidates"] = 20
        conf20 = forecaster._compute_confidence({})
        
        # Confidence should increase with more candidates
        assert 0.0 <= conf0 <= 1.0
        assert 0.0 <= conf5 <= 1.0
        assert 0.0 <= conf20 <= 1.0
        assert conf5 > conf0
        assert conf20 > conf5
    
    def test_weight_computation_high_confidence(self, forecaster):
        """Test weight computation for high confidence."""
        weights = forecaster._compute_weights(confidence=0.9)
        
        assert "gbrt" in weights
        assert "retrieval" in weights
        assert weights["gbrt"] > 0.5  # Should favor GBRT
        assert abs(weights["gbrt"] + weights["retrieval"] - 1.0) < 0.01
    
    def test_weight_computation_low_confidence(self, forecaster):
        """Test weight computation for low confidence."""
        weights = forecaster._compute_weights(confidence=0.4)
        
        assert "gbrt" in weights
        assert "retrieval" in weights
        assert abs(weights["gbrt"] - 0.5) < 0.2  # Should be more balanced
        assert abs(weights["gbrt"] + weights["retrieval"] - 1.0) < 0.01
    
    def test_combine_forecasts(self, forecaster):
        """Test forecast combination logic."""
        baseline = 100.0
        gbrt_residuals = {
            0.1: [-5.0] * 10,
            0.5: [0.0] * 10,
            0.9: [5.0] * 10,
        }
        retrieval_forecast = {
            0.1: [90.0] * 10,
            0.5: [100.0] * 10,
            0.9: [110.0] * 10,
        }
        weights = {"gbrt": 0.8, "retrieval": 0.2}
        
        combined = forecaster._combine_forecasts(
            baseline,
            gbrt_residuals,
            retrieval_forecast,
            weights,
            [0.1, 0.5, 0.9],
            10,
        )
        
        assert 0.1 in combined
        assert 0.5 in combined
        assert 0.9 in combined
        assert len(combined[0.5]) == 10
        
        # P50 should be close to baseline when residuals are zero
        assert abs(combined[0.5][0] - baseline) < 5.0
    
    def test_fallback_forecast(self, forecaster):
        """Test fallback forecast generation."""
        recent_window = [[100.0] for _ in range(10)]
        context = {
            "index": "NIFTY",
            "now_ms": 1700000000000,
            "underlying": 19500.0,
            "avg_iv": 0.15,
            "minutes_to_expiry": 300.0,
        }
        
        times, quantiles = forecaster._fallback_forecast(
            recent_window,
            context,
            [0.1, 0.5, 0.9],
            60,
            list(range(60)),
        )
        
        assert len(times) == 60
        assert 0.5 in quantiles
        assert len(quantiles[0.5]) == 60
        assert "fallback_used" in forecaster.last_meta


class TestEnsembleWithRetrieval:
    """Test ensemble with retrieval component enabled."""
    
    @pytest.fixture
    def config_with_retrieval(self, tmp_path):
        """Create config with retrieval enabled."""
        return EnsembleConfig(
            baseline_enabled=True,
            gbrt_enabled=False,
            retrieval_enabled=True,
            conformal_enabled=False,
            retrieval_root=tmp_path,  # Use temp directory
            retrieval_k=10,
            retrieval_window=30,
        )
    
    def test_initialization_with_retrieval(self, config_with_retrieval):
        """Test initialization with retrieval component."""
        forecaster = EnsembleForecaster(config_with_retrieval)
        
        # Retrieval may not initialize properly without data, but should not crash
        assert forecaster is not None


class TestEnsembleIntegration:
    """Integration tests for full ensemble pipeline."""
    
    def test_end_to_end_forecast(self):
        """Test complete forecast pipeline with all components disabled."""
        cfg = EnsembleConfig(
            baseline_enabled=True,
            gbrt_enabled=False,  # No model available in test
            retrieval_enabled=False,  # No data available in test
            conformal_enabled=True,
        )
        forecaster = EnsembleForecaster(cfg)
        
        # Prepare realistic input
        recent_window = [[95.0 + i * 0.5] for i in range(60)]
        context = {
            "index": "NIFTY",
            "now_ms": 1700000000000,
            "underlying": 19500.0,
            "avg_iv": 0.15,
            "minutes_to_expiry": 300.0,
            "live_rows": [],
        }
        
        # Generate forecast
        times, quantiles = forecaster.forecast_path(
            recent_window,
            context=context,
            quantiles=[0.1, 0.5, 0.9],
            horizon_minutes=60,
            bucket_ms=60000,
        )
        
        # Verify output
        assert len(times) == 60
        assert all(isinstance(t, int) for t in times)
        assert 0.1 in quantiles
        assert 0.5 in quantiles
        assert 0.9 in quantiles
        
        # Verify quantile ordering (P10 < P50 < P90)
        for i in range(len(quantiles[0.5])):
            p10 = quantiles[0.1][i]
            p50 = quantiles[0.5][i]
            p90 = quantiles[0.9][i]
            # Allow some tolerance for numerical issues
            assert p10 <= p50 + 1e-6
            assert p50 <= p90 + 1e-6
        
        # Verify metadata
        assert "confidence" in forecaster.last_meta
        assert "weight_gbrt" in forecaster.last_meta
        assert "weight_retrieval" in forecaster.last_meta


class TestConformalIntegration:
    """Test conformal prediction integration."""
    
    def test_conformal_update(self):
        """Test conformal band update."""
        cfg = EnsembleConfig(conformal_enabled=True)
        forecaster = EnsembleForecaster(cfg)
        
        # Update conformal band with observations
        for i in range(10):
            forecaster.update_conformal(predicted=100.0, actual=100.0 + i)
        
        # Verify conformal band is initialized
        assert forecaster._conformal_band is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
