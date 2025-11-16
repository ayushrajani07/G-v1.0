#!/usr/bin/env python3
"""
Hyperparameter Tuning for GBRT Quantile Models (Phase 2).

Performs grid search over hyperparameter space to find optimal configuration.

Based on ML_ARM_IMPLEMENTATION_ROADMAP.md Phase 2 specifications.

Usage:
    python scripts/ml/tune_gbrt_hyperparams.py \
        --dataset data/ml/training/nifty_tp_features_60d.csv \
        --output models/nifty_gbrt_quantile_tuned/ \
        --config configs/ml/nifty_tp_forecast_gbrt_quantile.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple

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
    """Load base configuration from JSON file."""
    logger.info(f"Loading base configuration from {config_path}")
    with open(config_path, "r") as f:
        config = json.load(f)
    return config


def load_dataset(dataset_path: str) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Load dataset and prepare features.
    
    Returns:
        Tuple of (X, y, feature_names)
    """
    logger.info(f"Loading dataset from {dataset_path}")
    df = pd.read_csv(dataset_path)
    
    # Get feature names
    fe = FeatureEngineer()
    all_features = fe.get_feature_names()
    feature_names = [f for f in all_features if f in df.columns]
    
    # Prepare data
    target_col = "tp_residual"
    df_subset = df[feature_names + [target_col]].dropna()
    
    X = df_subset[feature_names].values
    y = df_subset[target_col].values
    
    logger.info(f"Dataset: {len(X)} samples, {len(feature_names)} features")
    
    return X, y, feature_names


def get_search_space(base_config: Dict[str, Any]) -> Dict[str, List[Any]]:
    """Define hyperparameter search space.
    
    Args:
        base_config: Base configuration dictionary
        
    Returns:
        Dictionary mapping parameter names to lists of values to try
    """
    # Default search space based on roadmap
    search_space = {
        "n_estimators": [300, 500, 700],
        "max_depth": [3, 4, 5],
        "learning_rate": [0.02, 0.03, 0.05],
        "subsample": [0.7, 0.8, 0.9],
    }
    
    # Override with config if provided
    if "hyperparameter_search" in base_config:
        search_space.update(base_config["hyperparameter_search"])
    
    logger.info("Hyperparameter search space:")
    for param, values in search_space.items():
        logger.info(f"  {param}: {values}")
    
    # Compute total combinations
    total_combinations = 1
    for values in search_space.values():
        total_combinations *= len(values)
    logger.info(f"Total combinations to evaluate: {total_combinations}")
    
    return search_space


def compute_validation_score(
    y_true: np.ndarray,
    predictions: Dict[str, np.ndarray],
) -> float:
    """Compute validation score for hyperparameter optimization.
    
    Objective: Minimize validation MAE for P50 + average pinball loss
    
    Args:
        y_true: True target values
        predictions: Model predictions
        
    Returns:
        Validation score (lower is better)
    """
    # MAE for P50
    if "p50" in predictions:
        mae = np.mean(np.abs(y_true - predictions["p50"]))
    else:
        mae = 0.0
    
    # Average pinball loss
    pinball_losses = []
    for q_key in ["p10", "p50", "p90"]:
        if q_key in predictions:
            q = float(q_key[1:]) / 100.0
            y_pred = predictions[q_key]
            errors = y_true - y_pred
            pinball = np.where(errors >= 0, q * errors, (q - 1) * errors)
            pinball_losses.append(np.mean(pinball))
    
    avg_pinball = np.mean(pinball_losses) if pinball_losses else 0.0
    
    # Combined score: MAE + average pinball loss
    score = mae + avg_pinball
    
    return float(score)


def evaluate_hyperparameters(
    X: np.ndarray,
    y: np.ndarray,
    hyperparams: Dict[str, Any],
    quantiles: List[float] = [0.1, 0.5, 0.9],
    n_splits: int = 3,
) -> Tuple[float, Dict[str, Any]]:
    """Evaluate a hyperparameter configuration using cross-validation.
    
    Args:
        X: Feature matrix
        y: Target vector
        hyperparams: Hyperparameter dictionary
        quantiles: List of quantiles to predict
        n_splits: Number of CV folds
        
    Returns:
        Tuple of (average_score, detailed_metrics)
    """
    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_scores = []
    fold_metrics = []
    
    for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        # Train model
        model = QuantileRegressor(
            quantiles=quantiles,
            n_estimators=hyperparams.get("n_estimators", 500),
            max_depth=hyperparams.get("max_depth", 4),
            learning_rate=hyperparams.get("learning_rate", 0.03),
            subsample=hyperparams.get("subsample", 0.8),
            random_state=42,
            params={},
        )
        
        try:
            model.fit(X_train, y_train)
            
            # Predict on validation set
            predictions = model.predict(X_val)
            
            # Compute score
            score = compute_validation_score(y_val, predictions)
            fold_scores.append(score)
            
            # Compute MAE for logging
            mae = np.mean(np.abs(y_val - predictions["p50"])) if "p50" in predictions else 0.0
            fold_metrics.append({
                "fold": fold_idx + 1,
                "score": score,
                "mae_p50": mae,
            })
            
        except Exception as e:
            logger.warning(f"Fold {fold_idx + 1} failed: {e}")
            fold_scores.append(float('inf'))
    
    # Average score across folds
    avg_score = np.mean(fold_scores)
    
    detailed_metrics = {
        "avg_score": float(avg_score),
        "std_score": float(np.std(fold_scores)),
        "fold_scores": [float(s) for s in fold_scores],
        "fold_metrics": fold_metrics,
    }
    
    return avg_score, detailed_metrics


def grid_search(
    X: np.ndarray,
    y: np.ndarray,
    search_space: Dict[str, List[Any]],
    base_config: Dict[str, Any],
    n_cv_splits: int = 3,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Perform grid search over hyperparameter space.
    
    Args:
        X: Feature matrix
        y: Target vector
        search_space: Dictionary of hyperparameters to search
        base_config: Base configuration
        n_cv_splits: Number of CV splits
        
    Returns:
        Tuple of (best_hyperparams, all_results)
    """
    logger.info("Starting grid search...")
    
    # Generate all combinations
    param_names = list(search_space.keys())
    param_values = [search_space[name] for name in param_names]
    
    from itertools import product
    combinations = list(product(*param_values))
    
    logger.info(f"Evaluating {len(combinations)} combinations...")
    
    all_results = []
    best_score = float('inf')
    best_hyperparams = None
    
    quantiles = base_config.get("quantiles", [0.1, 0.5, 0.9])
    
    for idx, combo in enumerate(combinations):
        # Build hyperparameter dictionary
        hyperparams = dict(zip(param_names, combo))
        
        logger.info(f"\nEvaluation {idx + 1}/{len(combinations)}: {hyperparams}")
        
        start_time = time.time()
        
        # Evaluate
        score, metrics = evaluate_hyperparameters(
            X, y, hyperparams, quantiles=quantiles, n_splits=n_cv_splits
        )
        
        eval_time = time.time() - start_time
        
        logger.info(f"  Score: {score:.4f} (± {metrics['std_score']:.4f})")
        logger.info(f"  Time: {eval_time:.1f}s")
        
        # Store results
        result = {
            "hyperparams": hyperparams,
            "score": score,
            "metrics": metrics,
            "eval_time_seconds": eval_time,
        }
        all_results.append(result)
        
        # Update best
        if score < best_score:
            best_score = score
            best_hyperparams = hyperparams
            logger.info(f"  *** New best score: {best_score:.4f}")
    
    logger.info("\n" + "="*60)
    logger.info("Grid search completed!")
    logger.info(f"Best score: {best_score:.4f}")
    logger.info(f"Best hyperparameters: {best_hyperparams}")
    logger.info("="*60)
    
    return best_hyperparams, all_results


def save_tuning_results(
    output_dir: str,
    best_hyperparams: Dict[str, Any],
    all_results: List[Dict[str, Any]],
    base_config: Dict[str, Any],
):
    """Save hyperparameter tuning results.
    
    Args:
        output_dir: Output directory path
        best_hyperparams: Best hyperparameters found
        all_results: All evaluation results
        base_config: Base configuration
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Save tuning report
    report = {
        "best_hyperparams": best_hyperparams,
        "best_score": min(r["score"] for r in all_results),
        "all_results": all_results,
        "base_config": base_config,
    }
    
    report_path = output_path / "tuning_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Saved tuning report to {report_path}")
    
    # Save updated config with best hyperparameters
    updated_config = base_config.copy()
    if "hyperparameters" not in updated_config:
        updated_config["hyperparameters"] = {}
    updated_config["hyperparameters"].update(best_hyperparams)
    
    config_path = output_path / "best_config.json"
    with open(config_path, "w") as f:
        json.dump(updated_config, f, indent=2)
    logger.info(f"Saved best config to {config_path}")
    
    # Save results summary as CSV
    summary_data = []
    for result in all_results:
        row = result["hyperparams"].copy()
        row["score"] = result["score"]
        row["std_score"] = result["metrics"]["std_score"]
        summary_data.append(row)
    
    summary_df = pd.DataFrame(summary_data)
    summary_df = summary_df.sort_values("score")
    
    summary_path = output_path / "tuning_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    logger.info(f"Saved tuning summary to {summary_path}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Hyperparameter Tuning for GBRT Quantile Models"
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
        help="Output directory for tuning results"
    )
    
    parser.add_argument(
        "--config",
        type=str,
        help="Path to base configuration JSON (optional)"
    )
    
    parser.add_argument(
        "--cv-folds",
        type=int,
        default=3,
        help="Number of CV folds (default: 3)"
    )
    
    args = parser.parse_args()
    
    try:
        # Load base config if provided
        if args.config:
            base_config = load_config(args.config)
        else:
            base_config = {
                "quantiles": [0.1, 0.5, 0.9],
                "target": "tp_residual",
            }
        
        # Load dataset
        X, y, feature_names = load_dataset(args.dataset)
        
        # Get search space
        search_space = get_search_space(base_config)
        
        # Perform grid search
        best_hyperparams, all_results = grid_search(
            X, y, search_space, base_config, n_cv_splits=args.cv_folds
        )
        
        # Save results
        save_tuning_results(args.output, best_hyperparams, all_results, base_config)
        
        logger.info("\nHyperparameter tuning completed successfully!")
        logger.info(f"Results saved to {args.output}")
        
        # Print summary
        print("\n" + "="*60)
        print("TUNING SUMMARY")
        print("="*60)
        print(f"Best Hyperparameters:")
        for param, value in best_hyperparams.items():
            print(f"  {param}: {value}")
        print(f"\nBest Score: {min(r['score'] for r in all_results):.4f}")
        print(f"Results saved to: {args.output}")
        print("="*60)
        
    except Exception as e:
        logger.error(f"Hyperparameter tuning failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
