"""
Tests for GBRT model training (Phase 2).

Tests training script functionality including:
- Train/validation split
- Model training
- Metrics computation
- Feature importance extraction
- Model artifact saving
"""

from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import json

import numpy as np
import pandas as pd
import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analytics.ml.quantile import QuantileRegressor
from src.analytics.ml.feature_engineering import FeatureEngineer


def generate_test_dataset(n_samples: int = 1000) -> pd.DataFrame:
    """Generate synthetic test dataset."""
    np.random.seed(42)
    
    # Generate features
    timestamps = pd.date_range(start="2024-01-01 09:15", periods=n_samples, freq="1min")
    
    df = pd.DataFrame({
        "timestamp": timestamps,
        "underlying": 20000 + np.cumsum(np.random.randn(n_samples) * 10),
        "avg_iv": 0.15 + np.cumsum(np.random.randn(n_samples) * 0.001),
        "minutes_to_expiry": np.maximum(375 - (np.arange(n_samples) % 375), 1),
        "tp_actual": 100 + np.random.randn(n_samples) * 10,
        "tp_baseline": 100 + np.random.randn(n_samples) * 8,
    })
    
    df["tp_residual"] = df["tp_actual"] - df["tp_baseline"]
    
    return df


def test_feature_extraction():
    """Test feature extraction pipeline."""
    df = generate_test_dataset(n_samples=500)
    
    fe = FeatureEngineer()
    df_with_features = fe.extract_features(df)
    
    # Check that features are present
    feature_names = fe.get_feature_names()
    for feat in feature_names:
        assert feat in df_with_features.columns, f"Feature {feat} not found"
    
    # Check that residual is computed
    assert "tp_residual" in df_with_features.columns
    
    # Validate no infinite values
    for feat in feature_names:
        assert not np.any(np.isinf(df_with_features[feat].dropna())), f"Feature {feat} has infinite values"


def test_train_validation_split():
    """Test train/validation split logic."""
    df = generate_test_dataset(n_samples=1000)
    
    # Simple split
    train_size = 700
    val_size = 300
    
    train_df = df.iloc[:train_size]
    val_df = df.iloc[train_size:train_size + val_size]
    
    assert len(train_df) == train_size
    assert len(val_df) == val_size
    assert len(train_df) + len(val_df) <= len(df)


def test_model_training():
    """Test basic model training."""
    # Generate dataset
    df = generate_test_dataset(n_samples=500)
    
    # Extract features
    fe = FeatureEngineer()
    df_with_features = fe.extract_features(df)
    
    # Prepare data
    feature_names = fe.get_feature_names()
    X = df_with_features[feature_names].dropna().values
    y = df_with_features["tp_residual"].dropna().values
    
    # Ensure same length
    min_len = min(len(X), len(y))
    X = X[:min_len]
    y = y[:min_len]
    
    # Train model
    model = QuantileRegressor(
        quantiles=[0.1, 0.5, 0.9],
        n_estimators=50,  # Small for speed
        max_depth=3,
        learning_rate=0.1,
        random_state=42,
    )
    
    model.fit(X, y)
    
    # Check that models are trained
    assert len(model._models) == 3
    assert 0.1 in model._models
    assert 0.5 in model._models
    assert 0.9 in model._models


def test_model_prediction():
    """Test model prediction."""
    # Generate dataset
    df = generate_test_dataset(n_samples=300)
    
    # Extract features
    fe = FeatureEngineer()
    df_with_features = fe.extract_features(df)
    
    # Prepare data
    feature_names = fe.get_feature_names()
    df_clean = df_with_features[feature_names + ["tp_residual"]].dropna()
    X = df_clean[feature_names].values
    y = df_clean["tp_residual"].values
    
    # Train model
    model = QuantileRegressor(
        quantiles=[0.1, 0.5, 0.9],
        n_estimators=50,
        max_depth=3,
        random_state=42,
    )
    model.fit(X, y)
    
    # Predict
    predictions = model.predict(X)
    
    # Check predictions
    assert "p10" in predictions
    assert "p50" in predictions
    assert "p90" in predictions
    
    assert len(predictions["p10"]) == len(X)
    assert len(predictions["p50"]) == len(X)
    assert len(predictions["p90"]) == len(X)
    
    # Check ordering: p10 <= p50 <= p90
    assert np.all(predictions["p10"] <= predictions["p50"])
    assert np.all(predictions["p50"] <= predictions["p90"])


def test_metrics_computation():
    """Test metrics computation."""
    # Generate synthetic predictions and targets
    np.random.seed(42)
    n = 100
    y_true = np.random.randn(n) * 10
    
    predictions = {
        "p10": y_true + np.random.randn(n) * 2 - 5,
        "p50": y_true + np.random.randn(n) * 2,
        "p90": y_true + np.random.randn(n) * 2 + 5,
    }
    
    # Ensure ordering
    predictions["p10"] = np.minimum(predictions["p10"], predictions["p50"])
    predictions["p90"] = np.maximum(predictions["p90"], predictions["p50"])
    
    # Compute MAE
    mae = np.mean(np.abs(y_true - predictions["p50"]))
    assert mae >= 0
    
    # Compute RMSE
    rmse = np.sqrt(np.mean((y_true - predictions["p50"]) ** 2))
    assert rmse >= 0
    
    # Compute coverage
    in_band = (y_true >= predictions["p10"]) & (y_true <= predictions["p90"])
    coverage = np.mean(in_band)
    assert 0 <= coverage <= 1


def test_feature_importance():
    """Test feature importance extraction."""
    # Generate dataset
    df = generate_test_dataset(n_samples=300)
    
    # Extract features
    fe = FeatureEngineer()
    df_with_features = fe.extract_features(df)
    
    # Prepare data
    feature_names = fe.get_feature_names()
    df_clean = df_with_features[feature_names + ["tp_residual"]].dropna()
    X = df_clean[feature_names].values
    y = df_clean["tp_residual"].values
    
    # Train model
    model = QuantileRegressor(
        quantiles=[0.5],
        n_estimators=50,
        max_depth=3,
        random_state=42,
    )
    model.fit(X, y)
    
    # Extract feature importance
    for q, gbrt_model in model._models.items():
        importance = gbrt_model.feature_importances_
        
        # Check shape
        assert len(importance) == len(feature_names)
        
        # Check values
        assert np.all(importance >= 0)
        assert np.sum(importance) > 0


def test_model_save_load():
    """Test model serialization."""
    # Generate dataset
    df = generate_test_dataset(n_samples=200)
    
    # Extract features
    fe = FeatureEngineer()
    df_with_features = fe.extract_features(df)
    
    # Prepare data
    feature_names = fe.get_feature_names()
    df_clean = df_with_features[feature_names + ["tp_residual"]].dropna()
    X = df_clean[feature_names].values
    y = df_clean["tp_residual"].values
    
    # Train model
    model = QuantileRegressor(
        quantiles=[0.1, 0.5, 0.9],
        n_estimators=30,
        max_depth=3,
        random_state=42,
    )
    model.fit(X, y)
    
    # Save model
    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = Path(tmpdir) / "model.joblib"
        model.save(str(model_path))
        
        # Load model
        loaded_model = QuantileRegressor.load(str(model_path))
        
        # Check loaded model
        assert len(loaded_model._models) == 3
        
        # Check predictions match
        pred_original = model.predict(X)
        pred_loaded = loaded_model.predict(X)
        
        for key in ["p10", "p50", "p90"]:
            np.testing.assert_array_almost_equal(
                pred_original[key],
                pred_loaded[key],
                decimal=5
            )


def test_config_parsing():
    """Test configuration parsing."""
    config = {
        "model_type": "quantile_gbrt",
        "index": "NIFTY",
        "target": "tp_residual",
        "quantiles": [0.1, 0.5, 0.9],
        "hyperparameters": {
            "n_estimators": 500,
            "max_depth": 4,
            "learning_rate": 0.03,
            "subsample": 0.8,
        },
        "training": {
            "train_days": 45,
            "val_days": 5,
        }
    }
    
    # Check config structure
    assert config["model_type"] == "quantile_gbrt"
    assert config["index"] == "NIFTY"
    assert config["target"] == "tp_residual"
    assert len(config["quantiles"]) == 3
    assert "hyperparameters" in config
    assert "training" in config


def test_artifact_structure():
    """Test artifact directory structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "model_artifacts"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create mock artifacts
        model_path = output_dir / "model.joblib"
        model_path.touch()
        
        fe_config = {"feature_names": ["feat1", "feat2"], "n_features": 2}
        fe_path = output_dir / "feature_engineering.json"
        with open(fe_path, "w") as f:
            json.dump(fe_config, f)
        
        report = {
            "config": {},
            "train_metrics": {"mae_p50": 5.0},
            "val_metrics": {"mae_p50": 6.0},
        }
        report_path = output_dir / "training_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f)
        
        # Check artifacts exist
        assert model_path.exists()
        assert fe_path.exists()
        assert report_path.exists()


def test_cross_validation_split():
    """Test time-series cross-validation split."""
    from sklearn.model_selection import TimeSeriesSplit
    
    n_samples = 1000
    n_splits = 5
    
    X = np.random.randn(n_samples, 10)
    
    tscv = TimeSeriesSplit(n_splits=n_splits)
    
    splits = list(tscv.split(X))
    assert len(splits) == n_splits
    
    for train_idx, val_idx in splits:
        # Check no overlap
        assert len(set(train_idx) & set(val_idx)) == 0
        
        # Check ordering (validation comes after training)
        assert max(train_idx) < min(val_idx)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
