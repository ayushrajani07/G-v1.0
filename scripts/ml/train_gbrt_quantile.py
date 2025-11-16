#!/usr/bin/env python3
"""
Train GBRT Quantile Models for TP Forecasting (Phase 2).

Enhanced training script with:
- Train/validation split
- Walk-forward cross-validation
- Feature importance analysis
- Comprehensive metrics computation
- Training report generation

Based on ML_ARM_IMPLEMENTATION_ROADMAP.md Phase 2 specifications.

Usage:
    python scripts/ml/train_gbrt_quantile.py \
        --config configs/ml/nifty_tp_forecast_gbrt_quantile.json \
        --dataset data/ml/training/nifty_tp_features_60d.csv \
        --output models/nifty_gbrt_quantile/ \
        --tune-hyperparams
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analytics.ml.quantile import QuantileRegressor
from src.analytics.ml.feature_engineering import FeatureEngineer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> Dict[str, Any]:
    """Load training configuration from JSON file.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Configuration dictionary
    """
    logger.info(f"Loading configuration from {config_path}")
    with open(config_path, "r") as f:
        config = json.load(f)
    return config


def load_dataset(dataset_path: str, target_col: str = "tp_residual") -> Tuple[pd.DataFrame, List[str]]:
    """Load training dataset and identify features.
    
    Args:
        dataset_path: Path to dataset CSV
        target_col: Target column name
        
    Returns:
        Tuple of (dataframe, feature_names)
    """
    logger.info(f"Loading dataset from {dataset_path}")
    df = pd.read_csv(dataset_path)
    logger.info(f"Loaded {len(df)} samples")
    
    # Get feature names from FeatureEngineer
    fe = FeatureEngineer()
    all_features = fe.get_feature_names()
    
    # Filter to features present in dataset
    feature_names = [f for f in all_features if f in df.columns]
    logger.info(f"Found {len(feature_names)} features in dataset")
    
    return df, feature_names


def apply_feature_filter(
    feature_names: List[str],
    feature_config: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Apply feature filtering based on configuration.
    
    Args:
        feature_names: List of all feature names
        feature_config: Feature configuration dictionary
        
    Returns:
        Filtered list of feature names
    """
    if feature_config is None:
        return feature_names
    
    filtered = feature_names.copy()
    
    # Apply exclusions
    exclude = feature_config.get("exclude_features", [])
    if exclude:
        filtered = [f for f in filtered if f not in exclude]
        logger.info(f"Excluded {len(exclude)} features: {exclude}")
    
    # Apply feature group filters
    if not feature_config.get("use_lag_features", True):
        filtered = [f for f in filtered if not f.startswith("residual_lag")]
        logger.info("Excluded lag features")
    
    if not feature_config.get("use_market_features", True):
        market_prefixes = ["index_return", "avg_iv", "iv_change", "minutes_to_expiry", "time_of_day", "weekday"]
        filtered = [f for f in filtered if not any(f.startswith(p) for p in market_prefixes)]
        logger.info("Excluded market features")
    
    if not feature_config.get("use_regime_features", True):
        regime_prefixes = ["iv_percentile", "index_vol_percentile", "volume_ratio", "oi_change"]
        filtered = [f for f in filtered if not any(f.startswith(p) for p in regime_prefixes)]
        logger.info("Excluded regime features")
    
    logger.info(f"Using {len(filtered)} features after filtering")
    return filtered


def train_validation_split(
    df: pd.DataFrame,
    train_days: int = 45,
    val_days: int = 5,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split dataset into train and validation sets.
    
    Args:
        df: Input dataframe (assumed to be time-ordered)
        train_days: Number of days for training
        val_days: Number of days for validation
        
    Returns:
        Tuple of (train_df, val_df)
    """
    # Compute approximate split point (375 minutes per day)
    minutes_per_day = 375
    train_samples = train_days * minutes_per_day
    
    # Simple split: last val_days for validation, rest for training
    # In production, use timestamp-based splitting
    total_samples = len(df)
    val_samples = min(val_days * minutes_per_day, total_samples // 5)  # Max 20% validation
    train_samples = min(train_samples, total_samples - val_samples)
    
    train_df = df.iloc[:train_samples]
    val_df = df.iloc[train_samples:train_samples + val_samples]
    
    logger.info(f"Train set: {len(train_df)} samples, Validation set: {len(val_df)} samples")
    
    return train_df, val_df


def prepare_data(
    df: pd.DataFrame,
    feature_names: List[str],
    target_col: str = "tp_residual",
    drop_na: bool = True,
) -> Tuple[np.ndarray, np.ndarray]:
    """Prepare feature matrix and target vector.
    
    Args:
        df: Input dataframe
        feature_names: List of feature column names
        target_col: Target column name
        drop_na: Whether to drop rows with NaN values
        
    Returns:
        Tuple of (X, y) arrays
    """
    # Select features and target
    df_subset = df[feature_names + [target_col]].copy()
    
    # Drop NaN if requested
    if drop_na:
        before_len = len(df_subset)
        df_subset = df_subset.dropna()
        after_len = len(df_subset)
        if before_len > after_len:
            logger.info(f"Dropped {before_len - after_len} rows with NaN values")
    
    X = df_subset[feature_names].values
    y = df_subset[target_col].values
    
    return X, y


def train_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    config: Dict[str, Any],
) -> QuantileRegressor:
    """Train quantile regression models.
    
    Args:
        X_train: Training features
        y_train: Training targets
        config: Configuration dictionary
        
    Returns:
        Trained QuantileRegressor
    """
    quantiles = config.get("quantiles", [0.1, 0.5, 0.9])
    hyperparams = config.get("hyperparameters", {})
    
    logger.info(f"Training GBRT models for quantiles: {quantiles}")
    logger.info(f"Hyperparameters: {hyperparams}")
    
    start_time = time.time()
    
    # Create and train model
    model = QuantileRegressor(
        quantiles=quantiles,
        n_estimators=hyperparams.get("n_estimators", 500),
        max_depth=hyperparams.get("max_depth", 4),
        learning_rate=hyperparams.get("learning_rate", 0.03),
        subsample=hyperparams.get("subsample", 0.8),
        random_state=hyperparams.get("random_state", 42),
        params={
            k: v for k, v in hyperparams.items()
            if k not in ["n_estimators", "max_depth", "learning_rate", "subsample", "random_state"]
        },
    )
    
    model.fit(X_train, y_train)
    
    training_time = time.time() - start_time
    logger.info(f"Training completed in {training_time:.2f} seconds")
    
    return model


def compute_metrics(
    y_true: np.ndarray,
    predictions: Dict[str, np.ndarray],
    quantiles: List[float],
) -> Dict[str, Any]:
    """Compute evaluation metrics.
    
    Args:
        y_true: True target values
        predictions: Dictionary of predictions (keys: 'p10', 'p50', 'p90')
        quantiles: List of quantiles
        
    Returns:
        Dictionary of metrics
    """
    metrics = {}
    
    # Point forecast metrics (P50)
    if "p50" in predictions:
        y_pred = predictions["p50"]
        
        # MAE
        mae = np.mean(np.abs(y_true - y_pred))
        metrics["mae_p50"] = float(mae)
        
        # RMSE
        rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))
        metrics["rmse_p50"] = float(rmse)
        
        # MAPE (avoid division by zero)
        mask = np.abs(y_true) > 1e-8
        if mask.sum() > 0:
            mape = 100 * np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask]))
            metrics["mape_p50"] = float(mape)
        
        # Correlation
        if len(y_true) > 1:
            corr = np.corrcoef(y_true, y_pred)[0, 1]
            metrics["correlation_p50"] = float(corr)
    
    # Quantile forecast metrics
    if "p10" in predictions and "p90" in predictions:
        y_p10 = predictions["p10"]
        y_p90 = predictions["p90"]
        
        # Empirical coverage (should be ~80% for [P10, P90])
        in_band = (y_true >= y_p10) & (y_true <= y_p90)
        coverage = np.mean(in_band)
        metrics["empirical_coverage_p10_p90"] = float(coverage)
        
        # Average band width
        band_width = np.mean(y_p90 - y_p10)
        metrics["avg_band_width"] = float(band_width)
    
    # Pinball loss for all quantiles
    for q in quantiles:
        key = f"p{int(q*100)}"
        if key in predictions:
            y_pred = predictions[key]
            errors = y_true - y_pred
            pinball = np.where(
                errors >= 0,
                q * errors,
                (q - 1) * errors
            )
            metrics[f"pinball_loss_{key}"] = float(np.mean(pinball))
    
    return metrics


def extract_feature_importance(
    model: QuantileRegressor,
    feature_names: List[str],
    top_k: int = 15,
) -> Dict[str, Any]:
    """Extract feature importance from trained models.
    
    Args:
        model: Trained QuantileRegressor
        feature_names: List of feature names
        top_k: Number of top features to report
        
    Returns:
        Dictionary with feature importance information
    """
    importance_data = {}
    
    for q, gbrt_model in model._models.items():
        # Get feature importance from GBRT
        importance = gbrt_model.feature_importances_
        
        # Sort features by importance
        indices = np.argsort(importance)[::-1]
        
        # Store top K features
        top_features = []
        for i in range(min(top_k, len(indices))):
            idx = indices[i]
            top_features.append({
                "feature": feature_names[idx],
                "importance": float(importance[idx]),
            })
        
        importance_data[f"q{q:.2f}"] = top_features
    
    return importance_data


def cross_validate(
    X: np.ndarray,
    y: np.ndarray,
    config: Dict[str, Any],
    n_splits: int = 5,
) -> List[Dict[str, Any]]:
    """Perform time-series cross-validation.
    
    Args:
        X: Feature matrix
        y: Target vector
        config: Configuration dictionary
        n_splits: Number of CV folds
        
    Returns:
        List of metrics for each fold
    """
    logger.info(f"Starting {n_splits}-fold cross-validation")
    
    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_metrics = []
    
    for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X)):
        logger.info(f"Training fold {fold_idx + 1}/{n_splits}")
        
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        # Train model on fold
        model = train_model(X_train, y_train, config)
        
        # Evaluate on validation set
        predictions = model.predict(X_val)
        metrics = compute_metrics(y_val, predictions, config.get("quantiles", [0.1, 0.5, 0.9]))
        
        metrics["fold"] = fold_idx + 1
        metrics["train_size"] = len(train_idx)
        metrics["val_size"] = len(val_idx)
        
        fold_metrics.append(metrics)
        logger.info(f"Fold {fold_idx + 1} - MAE: {metrics.get('mae_p50', 0):.4f}, "
                   f"Coverage: {metrics.get('empirical_coverage_p10_p90', 0):.2%}")
    
    return fold_metrics


def save_model_artifacts(
    model: QuantileRegressor,
    output_dir: str,
    feature_names: List[str],
    config: Dict[str, Any],
    train_metrics: Dict[str, Any],
    val_metrics: Dict[str, Any],
    feature_importance: Dict[str, Any],
    cv_metrics: Optional[List[Dict[str, Any]]] = None,
):
    """Save model artifacts and metadata.
    
    Args:
        model: Trained model
        output_dir: Output directory path
        feature_names: List of feature names
        config: Configuration dictionary
        train_metrics: Training metrics
        val_metrics: Validation metrics
        feature_importance: Feature importance data
        cv_metrics: Cross-validation metrics (optional)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Save model
    model_path = output_path / "model.joblib"
    model.save(str(model_path))
    logger.info(f"Saved model to {model_path}")
    
    # Save feature engineering config
    fe_config = {
        "feature_names": feature_names,
        "n_features": len(feature_names),
    }
    fe_path = output_path / "feature_engineering.json"
    with open(fe_path, "w") as f:
        json.dump(fe_config, f, indent=2)
    logger.info(f"Saved feature config to {fe_path}")
    
    # Save training report
    report = {
        "config": config,
        "feature_names": feature_names,
        "n_features": len(feature_names),
        "train_metrics": train_metrics,
        "val_metrics": val_metrics,
        "feature_importance": feature_importance,
    }
    
    if cv_metrics:
        report["cv_metrics"] = cv_metrics
        # Compute CV summary statistics
        cv_summary = {}
        for key in ["mae_p50", "rmse_p50", "empirical_coverage_p10_p90"]:
            values = [m[key] for m in cv_metrics if key in m]
            if values:
                cv_summary[f"{key}_mean"] = float(np.mean(values))
                cv_summary[f"{key}_std"] = float(np.std(values))
        report["cv_summary"] = cv_summary
    
    report_path = output_path / "training_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Saved training report to {report_path}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Train GBRT Quantile Models (Phase 2)"
    )
    
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to training configuration JSON"
    )
    
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Path to training dataset CSV"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output directory for model artifacts"
    )
    
    parser.add_argument(
        "--cross-validate",
        action="store_true",
        help="Perform time-series cross-validation"
    )
    
    parser.add_argument(
        "--cv-folds",
        type=int,
        default=5,
        help="Number of cross-validation folds (default: 5)"
    )
    
    args = parser.parse_args()
    
    try:
        # Load configuration
        config = load_config(args.config)
        
        # Load dataset
        df, all_features = load_dataset(
            args.dataset,
            target_col=config.get("target", "tp_residual")
        )
        
        # Apply feature filtering
        feature_names = apply_feature_filter(
            all_features,
            config.get("feature_config")
        )
        
        # Train/validation split
        training_config = config.get("training", {})
        train_df, val_df = train_validation_split(
            df,
            train_days=training_config.get("train_days", 45),
            val_days=training_config.get("val_days", 5),
        )
        
        # Prepare data
        X_train, y_train = prepare_data(train_df, feature_names, config.get("target", "tp_residual"))
        X_val, y_val = prepare_data(val_df, feature_names, config.get("target", "tp_residual"))
        
        logger.info(f"Training samples: {len(X_train)}, Validation samples: {len(X_val)}")
        
        # Train model
        model = train_model(X_train, y_train, config)
        
        # Evaluate on training set
        train_predictions = model.predict(X_train)
        train_metrics = compute_metrics(y_train, train_predictions, config.get("quantiles", [0.1, 0.5, 0.9]))
        logger.info(f"Train MAE (P50): {train_metrics.get('mae_p50', 0):.4f}")
        logger.info(f"Train Coverage (P10-P90): {train_metrics.get('empirical_coverage_p10_p90', 0):.2%}")
        
        # Evaluate on validation set
        val_predictions = model.predict(X_val)
        val_metrics = compute_metrics(y_val, val_predictions, config.get("quantiles", [0.1, 0.5, 0.9]))
        logger.info(f"Validation MAE (P50): {val_metrics.get('mae_p50', 0):.4f}")
        logger.info(f"Validation Coverage (P10-P90): {val_metrics.get('empirical_coverage_p10_p90', 0):.2%}")
        
        # Extract feature importance
        feature_importance = extract_feature_importance(model, feature_names, top_k=15)
        logger.info("Top 5 features (P50):")
        for feat in feature_importance.get("q0.50", [])[:5]:
            logger.info(f"  {feat['feature']}: {feat['importance']:.4f}")
        
        # Cross-validation (optional)
        cv_metrics = None
        if args.cross_validate:
            # Use full dataset for CV
            X_full, y_full = prepare_data(df, feature_names, config.get("target", "tp_residual"))
            cv_metrics = cross_validate(X_full, y_full, config, n_splits=args.cv_folds)
        
        # Save artifacts
        save_model_artifacts(
            model=model,
            output_dir=args.output,
            feature_names=feature_names,
            config=config,
            train_metrics=train_metrics,
            val_metrics=val_metrics,
            feature_importance=feature_importance,
            cv_metrics=cv_metrics,
        )
        
        logger.info("Training completed successfully!")
        logger.info(f"Model artifacts saved to {args.output}")
        
        # Print summary
        print("\n" + "="*60)
        print("TRAINING SUMMARY")
        print("="*60)
        print(f"Model Type: {config.get('model_type', 'quantile_gbrt')}")
        print(f"Index: {config.get('index', 'N/A')}")
        print(f"Features: {len(feature_names)}")
        print(f"Training Samples: {len(X_train)}")
        print(f"Validation Samples: {len(X_val)}")
        print(f"\nValidation Metrics:")
        print(f"  MAE (P50): {val_metrics.get('mae_p50', 0):.4f}")
        print(f"  RMSE (P50): {val_metrics.get('rmse_p50', 0):.4f}")
        print(f"  Coverage (P10-P90): {val_metrics.get('empirical_coverage_p10_p90', 0):.2%}")
        print(f"\nModel saved to: {args.output}")
        print("="*60)
        
    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
