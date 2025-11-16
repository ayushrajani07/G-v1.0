"""
Unit tests for feature engineering module.

Tests all feature extraction functions and validation logic.
"""

import numpy as np
import pandas as pd
import pytest

from src.analytics.ml.feature_engineering import FeatureEngineer


@pytest.fixture
def sample_data():
    """Create sample data for testing."""
    np.random.seed(42)
    n = 100
    
    timestamps = pd.date_range("2024-01-01 09:15", periods=n, freq="1min")
    
    df = pd.DataFrame({
        "timestamp": timestamps,
        "tp_actual": 100 + np.cumsum(np.random.randn(n) * 0.5),
        "tp_baseline": 100 + np.cumsum(np.random.randn(n) * 0.3),
        "underlying": 20000 + np.cumsum(np.random.randn(n) * 10),
        "avg_iv": 0.15 + np.random.randn(n) * 0.01,
        "minutes_to_expiry": 375 - np.arange(n),
    })
    
    return df


def test_feature_engineer_init():
    """Test FeatureEngineer initialization."""
    fe = FeatureEngineer()
    assert fe.lag_periods == [1, 2, 5, 10, 30, 60]
    assert fe.rolling_windows == [5, 15, 30]
    assert fe.price_return_windows == [1, 5]


def test_extract_features_basic(sample_data):
    """Test basic feature extraction."""
    fe = FeatureEngineer()
    result = fe.extract_features(sample_data)
    
    # Check that residual is computed
    assert "tp_residual" in result.columns
    
    # Check shape
    assert len(result) == len(sample_data)
    
    # Check that features are added
    feature_names = fe.get_feature_names()
    for feat in feature_names:
        assert feat in result.columns, f"Missing feature: {feat}"


def test_lag_features(sample_data):
    """Test lag feature extraction."""
    fe = FeatureEngineer()
    result = fe.extract_features(sample_data)
    
    # Check lag features exist
    for lag in [1, 2, 5, 10, 30, 60]:
        assert f"residual_lag_{lag}" in result.columns
    
    # Check lag values are correct (for lag=1)
    residual = result["tp_residual"]
    lag_1 = result["residual_lag_1"]
    
    # Skip first row (will be NaN due to shift)
    for i in range(1, min(10, len(result))):
        if not pd.isna(lag_1.iloc[i]):
            assert np.isclose(lag_1.iloc[i], residual.iloc[i-1], rtol=1e-5)


def test_rolling_features(sample_data):
    """Test rolling statistics features."""
    fe = FeatureEngineer()
    result = fe.extract_features(sample_data)
    
    # Check rolling mean features
    for window in [5, 15, 30]:
        assert f"residual_rolling_mean_{window}" in result.columns
        assert f"residual_rolling_std_{window}" in result.columns
    
    # Verify rolling mean calculation for window=5
    residual = result["tp_residual"]
    rolling_mean_5 = result["residual_rolling_mean_5"]
    
    # Check a few values
    for i in range(5, min(15, len(result))):
        expected = residual.iloc[i-4:i+1].mean()
        assert np.isclose(rolling_mean_5.iloc[i], expected, rtol=1e-5)


def test_market_features(sample_data):
    """Test market feature extraction."""
    fe = FeatureEngineer()
    result = fe.extract_features(sample_data)
    
    # Check market features exist
    assert "index_return_1m" in result.columns
    assert "index_return_5m" in result.columns
    assert "avg_iv" in result.columns
    assert "iv_change_1m" in result.columns
    assert "minutes_to_expiry_norm" in result.columns
    assert "time_of_day_sin" in result.columns
    assert "time_of_day_cos" in result.columns
    assert "weekday" in result.columns
    
    # Check normalized minutes to expiry is in [0, 1]
    assert result["minutes_to_expiry_norm"].min() >= 0.0
    assert result["minutes_to_expiry_norm"].max() <= 1.0
    
    # Check time of day encoding (sin^2 + cos^2 = 1)
    sin_sq = result["time_of_day_sin"] ** 2
    cos_sq = result["time_of_day_cos"] ** 2
    assert np.allclose(sin_sq + cos_sq, 1.0, rtol=1e-5)
    
    # Check weekday is in [0, 6]
    assert result["weekday"].min() >= 0
    assert result["weekday"].max() <= 6


def test_regime_features(sample_data):
    """Test regime feature extraction."""
    fe = FeatureEngineer()
    result = fe.extract_features(sample_data)
    
    # Check regime features exist
    assert "iv_percentile" in result.columns
    assert "index_vol_percentile" in result.columns
    assert "volume_ratio" in result.columns
    assert "oi_change_rate" in result.columns
    
    # Check percentiles are in [0, 1]
    assert result["iv_percentile"].min() >= 0.0
    assert result["iv_percentile"].max() <= 1.0
    assert result["index_vol_percentile"].min() >= 0.0
    assert result["index_vol_percentile"].max() <= 1.0


def test_get_feature_names():
    """Test get_feature_names method."""
    fe = FeatureEngineer()
    feature_names = fe.get_feature_names()
    
    # Should have 24 features total
    assert len(feature_names) == 24
    
    # Check feature groups
    lag_features = [f for f in feature_names if "lag" in f]
    assert len(lag_features) == 6
    
    rolling_features = [f for f in feature_names if "rolling" in f]
    assert len(rolling_features) == 6  # 3 mean + 3 std
    
    market_features = [
        f for f in feature_names 
        if any(x in f for x in ["index_return", "avg_iv", "iv_change", 
                                 "minutes_to_expiry", "time_of_day", "weekday"])
    ]
    assert len(market_features) == 8
    
    regime_features = [
        f for f in feature_names
        if any(x in f for x in ["percentile", "volume_ratio", "oi_change"])
    ]
    assert len(regime_features) == 4


def test_validate_features_valid(sample_data):
    """Test feature validation with valid data."""
    fe = FeatureEngineer()
    result = fe.extract_features(sample_data)
    
    # Remove NaN values from lag features
    result = result.iloc[60:].copy()  # Skip first 60 rows
    result = result.fillna(0.0)
    
    is_valid, issues = fe.validate_features(result)
    assert is_valid
    assert len(issues) == 0


def test_validate_features_with_nan(sample_data):
    """Test feature validation detects NaN values."""
    fe = FeatureEngineer()
    result = fe.extract_features(sample_data)
    
    is_valid, issues = fe.validate_features(result, check_nan=True)
    # Should have issues due to lag features creating NaN
    assert not is_valid
    assert len(issues) > 0
    assert any("NaN" in issue for issue in issues)


def test_validate_features_with_inf():
    """Test feature validation detects infinite values."""
    fe = FeatureEngineer()
    
    # Create data with inf
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=10, freq="1min"),
        "tp_actual": [100] * 10,
        "tp_baseline": [90] * 10,
        "underlying": [20000] * 10,
        "avg_iv": [0.15] * 10,
        "minutes_to_expiry": [375] * 10,
    })
    
    result = fe.extract_features(df)
    # Inject inf value
    result.loc[5, "residual_lag_1"] = np.inf
    
    is_valid, issues = fe.validate_features(result, check_inf=True)
    assert not is_valid
    assert any("infinite" in issue for issue in issues)


def test_get_feature_statistics(sample_data):
    """Test feature statistics computation."""
    fe = FeatureEngineer()
    result = fe.extract_features(sample_data)
    
    stats = fe.get_feature_statistics(result)
    
    # Check that statistics exist for all features
    feature_names = fe.get_feature_names()
    for feat in feature_names:
        assert feat in stats
        assert "mean" in stats[feat]
        assert "std" in stats[feat]
        assert "min" in stats[feat]
        assert "max" in stats[feat]
        assert "p50" in stats[feat]


def test_edge_case_empty_dataframe():
    """Test with empty dataframe."""
    fe = FeatureEngineer()
    df = pd.DataFrame()
    
    with pytest.raises(Exception):
        fe.extract_features(df)


def test_edge_case_single_row():
    """Test with single row."""
    fe = FeatureEngineer()
    df = pd.DataFrame({
        "timestamp": [pd.Timestamp("2024-01-01 09:15")],
        "tp_actual": [100.0],
        "tp_baseline": [95.0],
        "underlying": [20000.0],
        "avg_iv": [0.15],
        "minutes_to_expiry": [375.0],
    })
    
    result = fe.extract_features(df)
    assert len(result) == 1
    assert "tp_residual" in result.columns


def test_custom_column_names():
    """Test with custom column names."""
    fe = FeatureEngineer()
    
    df = pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=20, freq="1min"),
        "total_premium": 100 + np.random.randn(20),
        "baseline_premium": 95 + np.random.randn(20),
        "spot_price": 20000 + np.random.randn(20) * 10,
        "implied_vol": 0.15 + np.random.randn(20) * 0.01,
        "time_to_expiry": 375 - np.arange(20),
    })
    
    result = fe.extract_features(
        df,
        tp_col="total_premium",
        tp_baseline_col="baseline_premium",
        index_price_col="spot_price",
        iv_col="implied_vol",
        minutes_to_expiry_col="time_to_expiry",
        timestamp_col="time",
    )
    
    assert "tp_residual" in result.columns
    assert len(result) == 20


def test_feature_continuity():
    """Test that features are continuous (no sudden jumps)."""
    fe = FeatureEngineer()
    
    # Create smooth data
    n = 100
    t = np.linspace(0, 10, n)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="1min"),
        "tp_actual": 100 + 5 * np.sin(t),
        "tp_baseline": 100 + 4 * np.sin(t),
        "underlying": 20000 + 100 * np.sin(t),
        "avg_iv": 0.15 + 0.01 * np.sin(t),
        "minutes_to_expiry": 375 - np.arange(n),
    })
    
    result = fe.extract_features(df)
    
    # Check that rolling means are smooth
    rolling_mean_5 = result["residual_rolling_mean_5"].dropna()
    # Differences should be small for smooth data
    diffs = rolling_mean_5.diff().abs()
    assert diffs.max() < 10.0  # Reasonable threshold


def test_residual_calculation(sample_data):
    """Test that residual is correctly calculated."""
    fe = FeatureEngineer()
    result = fe.extract_features(sample_data)
    
    expected_residual = sample_data["tp_actual"] - sample_data["tp_baseline"]
    actual_residual = result["tp_residual"]
    
    assert np.allclose(expected_residual, actual_residual, rtol=1e-5)


def test_missing_timestamp_column():
    """Test feature extraction without timestamp column."""
    fe = FeatureEngineer()
    
    df = pd.DataFrame({
        "tp_actual": [100, 101, 102],
        "tp_baseline": [95, 96, 97],
        "underlying": [20000, 20010, 20020],
        "avg_iv": [0.15, 0.15, 0.15],
        "minutes_to_expiry": [375, 374, 373],
    })
    
    result = fe.extract_features(df, timestamp_col="timestamp")
    
    # Should still extract features with default time values
    assert "time_of_day_sin" in result.columns
    assert "time_of_day_cos" in result.columns
    assert "weekday" in result.columns
