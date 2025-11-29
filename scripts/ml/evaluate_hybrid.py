#!/usr/bin/env python3
"""
Evaluate Hybrid Ensemble Performance (Phase 19).

Compares performance of:
1. Pure GBRT
2. Pure LSTM
3. Hybrid (Simple Average)
4. Hybrid (Weighted)

Usage:
    python scripts/ml/evaluate_hybrid.py \
        --gbrt-model models/nifty_gbrt_quantile/model.joblib \
        --lstm-model models/nifty_lstm/model.pt \
        --dataset data/ml/test/nifty_tp_features_test.csv \
        --output reports/hybrid_eval.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analytics.ml.quantile import QuantileRegressor
from src.analytics.ml.lstm_model import LSTMQuantileRegressor
from src.analytics.ml.meta_learner import EnsembleWeightLearner
from src.analytics.ml.feature_engineering import FeatureEngineer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def evaluate_model(
    model: Any, 
    X: np.ndarray, 
    y: np.ndarray, 
    model_type: str
) -> Dict[str, np.ndarray]:
    """Get predictions from a model."""
    if model_type == "gbrt":
        return model.predict(X)
    elif model_type == "lstm":
        # LSTM expects scaled input, assuming X is already prepared/scaled if needed
        # For this script, we'll assume X is compatible or handle scaling
        # In a real scenario, we'd need the scaler used during training
        return model.predict(X)
    return {}

def main():
    parser = argparse.ArgumentParser(description="Evaluate Hybrid Ensemble")
    parser.add_argument("--gbrt-model", required=True, help="Path to GBRT model")
    parser.add_argument("--lstm-model", required=True, help="Path to LSTM model")
    parser.add_argument("--dataset", required=True, help="Path to test dataset")
    parser.add_argument("--output", required=True, help="Output report path")
    
    args = parser.parse_args()
    
    # Load Data
    logger.info(f"Loading dataset from {args.dataset}")
    df = pd.read_csv(args.dataset)
    
    # Feature Engineering (to get feature names)
    fe = FeatureEngineer()
    feature_names = [f for f in fe.get_feature_names() if f in df.columns]
    
    X = df[feature_names].fillna(0.0).values
    y = df["tp_residual"].values
    
    # Load Models
    logger.info("Loading models...")
    try:
        gbrt = QuantileRegressor.load(args.gbrt_model)
        lstm = LSTMQuantileRegressor.load(args.lstm_model)
    except Exception as e:
        logger.error(f"Failed to load models: {e}")
        sys.exit(1)
        
    # Get Predictions
    logger.info("Generating predictions...")
    preds_gbrt = gbrt.predict(X)
    preds_lstm = lstm.predict(X) # Note: LSTM might need scaling, skipping for simplicity in this scaffold
    
    # Evaluate per quantile
    results = {}
    quantiles = ["q0.10", "q0.50", "q0.90"]
    
    # Prepare data for meta-learner (using q0.50 as proxy for central tendency)
    meta_preds = {
        "gbrt": preds_gbrt.get("q0.50", np.zeros_like(y)),
        "lstm": preds_lstm.get("q0.50", np.zeros_like(y))
    }
    
    # Train Meta-Learner (on first half of test data, evaluate on second half)
    split_idx = len(y) // 2
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    meta_preds_train = {k: v[:split_idx] for k, v in meta_preds.items()}
    meta_preds_test = {k: v[split_idx:] for k, v in meta_preds.items()}
    
    learner = EnsembleWeightLearner(components=["gbrt", "lstm"])
    weights = learner.fit(meta_preds_train, y_train)
    
    logger.info(f"Learned Weights: {weights}")
    
    # Calculate Metrics on Test Set
    metrics = {}
    
    for q in quantiles:
        if q not in preds_gbrt or q not in preds_lstm:
            continue
            
        p_gbrt = preds_gbrt[q][split_idx:]
        p_lstm = preds_lstm[q][split_idx:]
        
        # Hybrid (Simple Average)
        p_avg = (p_gbrt + p_lstm) / 2
        
        # Hybrid (Weighted)
        p_weighted = (weights["gbrt"] * p_gbrt + weights["lstm"] * p_lstm)
        
        # Calculate MAE
        mae_gbrt = mean_absolute_error(y_test, p_gbrt)
        mae_lstm = mean_absolute_error(y_test, p_lstm)
        mae_avg = mean_absolute_error(y_test, p_avg)
        mae_weighted = mean_absolute_error(y_test, p_weighted)
        
        metrics[q] = {
            "mae_gbrt": mae_gbrt,
            "mae_lstm": mae_lstm,
            "mae_avg": mae_avg,
            "mae_weighted": mae_weighted,
            "best_model": min(
                ("gbrt", mae_gbrt), 
                ("lstm", mae_lstm), 
                ("avg", mae_avg), 
                ("weighted", mae_weighted),
                key=lambda x: x[1]
            )[0]
        }
        
    logger.info(f"Evaluation Results: {json.dumps(metrics, indent=2)}")
    
    # Save Report
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump({
            "weights": weights,
            "metrics": metrics
        }, f, indent=2)

if __name__ == "__main__":
    main()
