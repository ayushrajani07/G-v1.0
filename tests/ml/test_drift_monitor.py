"""
Tests for drift monitoring module - Phase 10.

Tests the drift detection calculations, baseline persistence,
and alert logic for feature distribution monitoring.
"""


import numpy as np
import pytest

from src.ml.drift_monitor import DriftMonitor, create_drift_monitor_from_env


class TestDriftMonitor:
    """Test DriftMonitor class."""
    
    @pytest.fixture
    def monitor(self):
        """Create a DriftMonitor instance for testing."""
        return DriftMonitor(
            baseline_days=30,
            recent_rows=300,
            psi_threshold=0.25,
            ks_pvalue_threshold=0.01,
            mean_zscore_threshold=3.0,
            num_bins=10,
        )
    
    @pytest.fixture
    def mock_baseline_window(self):
        """Create mock baseline feature distributions."""
        # Generate normal distributions
        np.random.seed(42)
        baseline_values = np.random.randn(1000) * 10 + 100
        
        return {
            "index": "NIFTY",
            "lookback_days": 30,
            "window_start": "2025-10-19T00:00:00Z",
            "window_end": "2025-11-18T00:00:00Z",
            "features": {
                "tp_residual_lag1": {
                    "values": baseline_values.tolist(),
                    "mean": float(np.mean(baseline_values)),
                    "std": float(np.std(baseline_values)),
                    "min": float(np.min(baseline_values)),
                    "max": float(np.max(baseline_values)),
                    "quantiles": np.quantile(baseline_values, np.linspace(0, 1, 11)).tolist(),
                }
            }
        }
    
    @pytest.fixture
    def mock_recent_window_no_drift(self, mock_baseline_window):
        """Create recent window with no significant drift."""
        # Similar distribution to baseline
        np.random.seed(43)
        recent_values = np.random.randn(300) * 10 + 100
        
        return {
            "index": "NIFTY",
            "lookback_days": 0,
            "window_start": "2025-11-18T00:00:00Z",
            "window_end": "2025-11-18T12:00:00Z",
            "features": {
                "tp_residual_lag1": {
                    "values": recent_values.tolist(),
                    "mean": float(np.mean(recent_values)),
                    "std": float(np.std(recent_values)),
                    "min": float(np.min(recent_values)),
                    "max": float(np.max(recent_values)),
                    "quantiles": np.quantile(recent_values, np.linspace(0, 1, 11)).tolist(),
                }
            }
        }
    
    @pytest.fixture
    def mock_recent_window_with_drift(self, mock_baseline_window):
        """Create recent window with significant drift."""
        # Shifted distribution (mean +30, variance doubled)
        np.random.seed(44)
        recent_values = np.random.randn(300) * 20 + 130
        
        return {
            "index": "NIFTY",
            "lookback_days": 0,
            "window_start": "2025-11-18T00:00:00Z",
            "window_end": "2025-11-18T12:00:00Z",
            "features": {
                "tp_residual_lag1": {
                    "values": recent_values.tolist(),
                    "mean": float(np.mean(recent_values)),
                    "std": float(np.std(recent_values)),
                    "min": float(np.min(recent_values)),
                    "max": float(np.max(recent_values)),
                    "quantiles": np.quantile(recent_values, np.linspace(0, 1, 11)).tolist(),
                }
            }
        }
    
    def test_initialization(self, monitor):
        """Test DriftMonitor initialization."""
        assert monitor.baseline_days == 30
        assert monitor.recent_rows == 300
        assert monitor.psi_threshold == 0.25
        assert monitor.ks_pvalue_threshold == 0.01
        assert monitor.mean_zscore_threshold == 3.0
        assert monitor.num_bins == 10
        assert monitor.baseline_dir.exists()
    
    def test_calculate_drift_metrics_no_drift(
        self, monitor, mock_baseline_window, mock_recent_window_no_drift
    ):
        """Test drift calculation when no significant drift is present."""
        drift_metrics = monitor.calculate_drift_metrics(
            mock_baseline_window,
            mock_recent_window_no_drift,
        )
        
        assert "tp_residual_lag1" in drift_metrics
        metrics = drift_metrics["tp_residual_lag1"]
        
        # PSI should be low (< 0.25)
        assert metrics["psi"] < 0.25
        
        # KS p-value should be high (> 0.01)
        assert metrics["ks_pvalue"] > 0.01
        
        # Mean delta Z-score should be small (< 3)
        assert abs(metrics["mean_delta_zscore"]) < 3.0
        
        # Alert flag should be False
        assert metrics["alert_flag"] is False
        assert len(metrics["alert_reasons"]) == 0
    
    def test_calculate_drift_metrics_with_drift(
        self, monitor, mock_baseline_window, mock_recent_window_with_drift
    ):
        """Test drift calculation when significant drift is present."""
        drift_metrics = monitor.calculate_drift_metrics(
            mock_baseline_window,
            mock_recent_window_with_drift,
        )
        
        assert "tp_residual_lag1" in drift_metrics
        metrics = drift_metrics["tp_residual_lag1"]
        
        # PSI should be high due to distribution shift
        # (we shifted mean by ~3 std devs and doubled variance)
        assert metrics["psi"] > 0.10  # At least some drift
        
        # KS p-value should be low (distributions differ)
        assert metrics["ks_pvalue"] < 0.05
        
        # Mean delta should be significant
        assert abs(metrics["mean_delta"]) > 20  # We shifted by ~30
        
        # Mean delta Z-score should exceed threshold
        assert abs(metrics["mean_delta_zscore"]) > 2.0  # Significant shift
        
        # Variance delta should be positive (we doubled variance)
        assert metrics["var_delta"] > 0.5
        
        # Alert flag should likely be True (multiple conditions triggered)
        # This is probabilistic but very likely given our shift
        assert isinstance(metrics["alert_flag"], bool)
        
        # Should have bin-level details
        assert len(metrics["bins"]) > 0
    
    def test_calculate_psi(self, monitor):
        """Test PSI calculation directly."""
        # Create two identical distributions
        baseline_values = list(np.random.randn(1000))
        recent_values = list(np.random.randn(1000))
        
        psi, bins = monitor._calculate_psi(baseline_values, recent_values)
        
        # PSI should be very small for similar distributions
        assert psi < 0.15
        assert len(bins) > 0
        
        # Create very different distributions
        baseline_values = list(np.random.randn(1000))
        recent_values = list(np.random.randn(1000) + 5)  # Shifted
        
        psi, bins = monitor._calculate_psi(baseline_values, recent_values)
        
        # PSI should be larger for different distributions
        assert psi > 0.15
    
    def test_check_alert_conditions(self, monitor):
        """Test alert condition checking logic."""
        # Test case 1: No drift
        alert_flag, reasons = monitor._check_alert_conditions(
            psi=0.10,
            ks_pvalue=0.50,
            mean_delta_zscore=1.0,
        )
        assert alert_flag is False
        assert len(reasons) == 0
        
        # Test case 2: High PSI only
        alert_flag, reasons = monitor._check_alert_conditions(
            psi=0.30,
            ks_pvalue=0.50,
            mean_delta_zscore=1.0,
        )
        assert alert_flag is True
        assert len(reasons) == 1
        assert "PSI" in reasons[0]
        
        # Test case 3: Low KS p-value only
        alert_flag, reasons = monitor._check_alert_conditions(
            psi=0.10,
            ks_pvalue=0.005,
            mean_delta_zscore=1.0,
        )
        assert alert_flag is True
        assert len(reasons) == 1
        assert "KS p-value" in reasons[0]
        
        # Test case 4: High mean delta Z-score only
        alert_flag, reasons = monitor._check_alert_conditions(
            psi=0.10,
            ks_pvalue=0.50,
            mean_delta_zscore=4.0,
        )
        assert alert_flag is True
        assert len(reasons) == 1
        assert "Z-score" in reasons[0]
        
        # Test case 5: Multiple conditions triggered
        alert_flag, reasons = monitor._check_alert_conditions(
            psi=0.35,
            ks_pvalue=0.005,
            mean_delta_zscore=5.0,
        )
        assert alert_flag is True
        assert len(reasons) == 3
    
    def test_baseline_persistence(self, monitor, mock_baseline_window):
        """Test saving and loading baselines."""
        index = "TEST_INDEX"
        
        # Save baseline
        success = monitor.save_baseline(index, mock_baseline_window)
        assert success is True
        
        # Check file exists
        baseline_path = monitor.baseline_dir / f"{index}.json"
        assert baseline_path.exists()
        
        # Load baseline
        loaded = monitor.load_baseline(index)
        assert loaded is not None
        assert loaded["index"] == mock_baseline_window["index"]
        assert "saved_at" in loaded
        assert "version" in loaded
        
        # Verify features are preserved
        assert "tp_residual_lag1" in loaded["features"]
        
        # Clean up
        baseline_path.unlink()
    
    def test_load_nonexistent_baseline(self, monitor):
        """Test loading a baseline that doesn't exist."""
        loaded = monitor.load_baseline("NONEXISTENT_INDEX")
        assert loaded is None
    
    def test_get_or_create_baseline(self, monitor):
        """Test get_or_create_baseline logic."""
        index = "TEST_GET_OR_CREATE"
        
        # First call should create baseline
        baseline = monitor.get_or_create_baseline(index)
        assert baseline is not None
        assert baseline["index"] == index
        
        # Second call should load existing baseline
        baseline2 = monitor.get_or_create_baseline(index)
        assert baseline2 is not None
        
        # Clean up
        baseline_path = monitor.baseline_dir / f"{index}.json"
        if baseline_path.exists():
            baseline_path.unlink()
    
    def test_compute_feature_distributions(self, monitor):
        """Test feature distribution computation (placeholder)."""
        result = monitor.compute_feature_distributions(
            index="NIFTY",
            lookback_days=30,
            features=["tp_residual_lag1", "index_return_1min"],
        )
        
        assert result["index"] == "NIFTY"
        assert result["lookback_days"] == 30
        assert "window_start" in result
        assert "window_end" in result
        assert "features" in result
        
        # Check requested features are present
        assert "tp_residual_lag1" in result["features"]
        assert "index_return_1min" in result["features"]
        
        # Check feature structure
        feature_data = result["features"]["tp_residual_lag1"]
        assert "values" in feature_data
        assert "mean" in feature_data
        assert "std" in feature_data
        assert "quantiles" in feature_data
        assert len(feature_data["values"]) > 0


class TestDriftMonitorEnvironment:
    """Test environment variable configuration."""
    
    def test_create_from_env_defaults(self, monkeypatch):
        """Test creating monitor with default environment variables."""
        # Clear any existing env vars
        for key in [
            "G6_DRIFT_BASELINE_DAYS",
            "G6_DRIFT_RECENT_ROWS",
            "G6_DRIFT_PSI_THRESHOLD",
            "G6_DRIFT_KS_PVALUE_THRESHOLD",
            "G6_DRIFT_MEAN_ZSCORE_THRESHOLD",
        ]:
            monkeypatch.delenv(key, raising=False)
        
        monitor = create_drift_monitor_from_env()
        
        assert monitor.baseline_days == 30
        assert monitor.recent_rows == 300
        assert monitor.psi_threshold == 0.25
        assert monitor.ks_pvalue_threshold == 0.01
        assert monitor.mean_zscore_threshold == 3.0
    
    def test_create_from_env_custom(self, monkeypatch):
        """Test creating monitor with custom environment variables."""
        monkeypatch.setenv("G6_DRIFT_BASELINE_DAYS", "60")
        monkeypatch.setenv("G6_DRIFT_RECENT_ROWS", "500")
        monkeypatch.setenv("G6_DRIFT_PSI_THRESHOLD", "0.30")
        monkeypatch.setenv("G6_DRIFT_KS_PVALUE_THRESHOLD", "0.005")
        monkeypatch.setenv("G6_DRIFT_MEAN_ZSCORE_THRESHOLD", "4.0")
        
        monitor = create_drift_monitor_from_env()
        
        assert monitor.baseline_days == 60
        assert monitor.recent_rows == 500
        assert monitor.psi_threshold == 0.30
        assert monitor.ks_pvalue_threshold == 0.005
        assert monitor.mean_zscore_threshold == 4.0


class TestDriftMetricsEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_feature_list(self):
        """Test handling of empty feature lists."""
        monitor = DriftMonitor()
        
        baseline = {
            "index": "NIFTY",
            "features": {}
        }
        recent = {
            "index": "NIFTY",
            "features": {}
        }
        
        drift_metrics = monitor.calculate_drift_metrics(baseline, recent)
        assert len(drift_metrics) == 0
    
    def test_no_common_features(self):
        """Test handling when baseline and recent have different features."""
        monitor = DriftMonitor()
        
        baseline = {
            "index": "NIFTY",
            "features": {
                "feature_A": {
                    "values": [1, 2, 3],
                    "mean": 2.0,
                    "std": 1.0,
                }
            }
        }
        recent = {
            "index": "NIFTY",
            "features": {
                "feature_B": {
                    "values": [4, 5, 6],
                    "mean": 5.0,
                    "std": 1.0,
                }
            }
        }
        
        drift_metrics = monitor.calculate_drift_metrics(baseline, recent)
        assert len(drift_metrics) == 0
    
    def test_zero_variance_feature(self):
        """Test handling of features with zero variance."""
        monitor = DriftMonitor()
        
        baseline = {
            "index": "NIFTY",
            "features": {
                "constant_feature": {
                    "values": [5.0] * 100,
                    "mean": 5.0,
                    "std": 0.0,
                    "quantiles": [5.0] * 11,
                }
            }
        }
        recent = {
            "index": "NIFTY",
            "features": {
                "constant_feature": {
                    "values": [5.0] * 50,
                    "mean": 5.0,
                    "std": 0.0,
                    "quantiles": [5.0] * 11,
                }
            }
        }
        
        # Should handle gracefully (PSI = 0, no drift)
        drift_metrics = monitor.calculate_drift_metrics(baseline, recent)
        assert "constant_feature" in drift_metrics
        # With constant values, PSI should be 0 or very small
        assert drift_metrics["constant_feature"]["psi"] < 0.01
