"""
Integration tests for dataset generation script.

Tests the end-to-end dataset generation pipeline.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import pytest
import tempfile
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ml.generate_training_dataset import (
    generate_synthetic_data,
    compute_baseline,
    extract_features,
    validate_dataset,
)


def test_generate_synthetic_data():
    """Test synthetic data generation."""
    df = generate_synthetic_data(index="NIFTY", days=2)
    
    # Check shape (approximately 2 days * 375 minutes/day)
    assert len(df) > 700
    assert len(df) < 800
    
    # Check columns
    required_cols = [
        "timestamp", "index", "underlying", "ce_iv", "pe_iv",
        "avg_iv", "tp_actual", "minutes_to_expiry"
    ]
    for col in required_cols:
        assert col in df.columns, f"Missing column: {col}"
    
    # Check data types
    assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])
    assert df["index"].iloc[0] == "NIFTY"
    
    # Check value ranges
    assert df["underlying"].min() > 0
    assert df["avg_iv"].min() > 0
    assert df["tp_actual"].min() > 0
    assert df["minutes_to_expiry"].min() >= 1
    assert df["minutes_to_expiry"].max() <= 375


def test_compute_baseline():
    """Test baseline computation."""
    df = generate_synthetic_data(index="NIFTY", days=1)
    result = compute_baseline(df, k=1.0)
    
    # Check baseline columns added
    assert "tp_baseline" in result.columns
    assert "tp_residual" in result.columns
    
    # Check baseline values are positive
    assert result["tp_baseline"].min() > 0
    
    # Check residual calculation
    expected_residual = result["tp_actual"] - result["tp_baseline"]
    assert np.allclose(result["tp_residual"], expected_residual, rtol=1e-5)
    
    # Check correlation (should be high for synthetic data)
    corr = result["tp_actual"].corr(result["tp_baseline"])
    assert corr > 0.85, f"Baseline correlation {corr} too low"


def test_extract_features():
    """Test feature extraction."""
    df = generate_synthetic_data(index="NIFTY", days=1)
    df = compute_baseline(df, k=1.0)
    result = extract_features(df)
    
    # Check that all 24 features are present
    expected_features = [
        # Lag features (6)
        "residual_lag_1", "residual_lag_2", "residual_lag_5",
        "residual_lag_10", "residual_lag_30", "residual_lag_60",
        # Rolling mean (3)
        "residual_rolling_mean_5", "residual_rolling_mean_15",
        "residual_rolling_mean_30",
        # Rolling std (3)
        "residual_rolling_std_5", "residual_rolling_std_15",
        "residual_rolling_std_30",
        # Market features (8)
        "index_return_1m", "index_return_5m", "avg_iv", "iv_change_1m",
        "minutes_to_expiry_norm", "time_of_day_sin", "time_of_day_cos",
        "weekday",
        # Regime features (4)
        "iv_percentile", "index_vol_percentile", "volume_ratio",
        "oi_change_rate",
    ]
    
    for feat in expected_features:
        assert feat in result.columns, f"Missing feature: {feat}"
    
    # Check feature values
    assert result["minutes_to_expiry_norm"].min() >= 0.0
    assert result["minutes_to_expiry_norm"].max() <= 1.0
    
    # Check time encoding
    sin_sq = result["time_of_day_sin"] ** 2
    cos_sq = result["time_of_day_cos"] ** 2
    assert np.allclose(sin_sq + cos_sq, 1.0, rtol=1e-5)


def test_validate_dataset():
    """Test dataset validation."""
    df = generate_synthetic_data(index="NIFTY", days=1)
    df = compute_baseline(df, k=1.0)
    df = extract_features(df)
    
    validation = validate_dataset(df, min_completeness=0.9)
    
    # Check validation structure
    assert "total_samples" in validation
    assert "features_count" in validation
    assert "completeness" in validation
    assert "nan_counts" in validation
    assert "inf_counts" in validation
    assert "passed" in validation
    assert "issues" in validation
    
    # Check metrics
    assert validation["total_samples"] == len(df)
    # Phase 7: With enhanced index features by default, we have 32 features
    assert validation["features_count"] == 32
    assert "baseline_correlation" in validation
    assert validation["baseline_correlation"] > 0.85


def test_end_to_end_pipeline():
    """Test complete pipeline from generation to validation."""
    # Generate synthetic data
    df = generate_synthetic_data(index="NIFTY", days=2)
    assert len(df) > 0
    
    # Compute baseline
    df = compute_baseline(df, k=1.0)
    assert "tp_baseline" in df.columns
    
    # Extract features
    df = extract_features(df)
    assert len([c for c in df.columns if "residual_lag" in c]) == 6
    
    # Validate
    validation = validate_dataset(df)
    assert validation["passed"]


def test_different_indices():
    """Test generation for different indices."""
    for index in ["NIFTY", "BANKNIFTY"]:
        df = generate_synthetic_data(index=index, days=1)
        assert df["index"].iloc[0] == index
        assert len(df) > 300  # At least one day
        
        # Check that base values differ by index
        if index == "BANKNIFTY":
            assert df["underlying"].mean() > 30000  # Higher base price
        else:
            assert df["underlying"].mean() < 30000


def test_validation_detects_low_correlation():
    """Test that validation detects poor baseline correlation."""
    df = generate_synthetic_data(index="NIFTY", days=1)
    
    # Break the correlation by randomizing TP
    df["tp_actual"] = np.random.randn(len(df)) * 100 + 100
    
    df = compute_baseline(df, k=1.0)
    df = extract_features(df)
    
    validation = validate_dataset(df, min_completeness=0.9)
    
    # Should fail due to low correlation
    assert not validation["passed"]
    assert any("correlation" in issue.lower() for issue in validation["issues"])


def test_different_k_coefficients():
    """Test baseline with different k coefficients."""
    df = generate_synthetic_data(index="NIFTY", days=1)
    
    df1 = compute_baseline(df.copy(), k=1.0)
    df2 = compute_baseline(df.copy(), k=2.0)
    
    # With k=2.0, baseline should be roughly 2x
    ratio = df2["tp_baseline"].mean() / df1["tp_baseline"].mean()
    assert 1.9 < ratio < 2.1, f"K scaling incorrect, ratio={ratio}"


def test_feature_statistics():
    """Test feature statistics computation."""
    from src.analytics.ml.feature_engineering import FeatureEngineer
    
    df = generate_synthetic_data(index="NIFTY", days=1)
    df = compute_baseline(df, k=1.0)
    df = extract_features(df)
    
    fe = FeatureEngineer()  # Default has enhanced index features
    stats = fe.get_feature_statistics(df)
    
    # Check that stats exist for all features (32 with enhanced index by default)
    assert len(stats) == 32
    
    # Check stat structure
    for feat_name, feat_stats in stats.items():
        assert "mean" in feat_stats
        assert "std" in feat_stats
        assert "min" in feat_stats
        assert "max" in feat_stats
        assert "p50" in feat_stats
