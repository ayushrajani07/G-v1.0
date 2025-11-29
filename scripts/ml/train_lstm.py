#!/usr/bin/env python3
"""
Train LSTM Quantile Models for TP Forecasting (Phase 18).

Trains an LSTM model for quantile regression on residual forecasting.

Usage:
    python scripts/ml/train_lstm.py \
        --config configs/ml/nifty_tp_forecast_lstm.json \
        --dataset data/ml/training/nifty_tp_features_60d.csv \
        --output models/nifty_lstm/
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
from sklearn.preprocessing import StandardScaler

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analytics.ml.lstm_model import LSTMQuantileRegressor
from src.analytics.ml.feature_engineering import FeatureEngineer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def load_config(config_path: str) -> Dict[str, Any]:
    logger.info(f"Loading configuration from {config_path}")
    with open(config_path, "r") as f:
        config = json.load(f)
    return config

def load_dataset(dataset_path: str) -> Tuple[pd.DataFrame, List[str]]:
    logger.info(f"Loading dataset from {dataset_path}")
    df = pd.read_csv(dataset_path)
    logger.info(f"Loaded {len(df)} samples")
    
    fe = FeatureEngineer()
    all_features = fe.get_feature_names()
    feature_names = [f for f in all_features if f in df.columns]
    logger.info(f"Found {len(feature_names)} features in dataset")
    
    return df, feature_names

def prepare_sequences(
    X: np.ndarray, 
    y: np.ndarray, 
    seq_len: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Convert 2D data to 3D sequences for LSTM."""
    X_seq, y_seq = [], []
    for i in range(len(X) - seq_len):
        X_seq.append(X[i:i+seq_len])
        y_seq.append(y[i+seq_len])
    return np.array(X_seq), np.array(y_seq)

def train_model(
    config: Dict[str, Any],
    df: pd.DataFrame,
    feature_names: List[str],
    output_dir: Path
) -> None:
    target_col = config.get("target_col", "tp_residual")
    quantiles = config.get("quantiles", [0.1, 0.5, 0.9])
    seq_len = config.get("seq_len", 10)
    
    # Prepare data
    X = df[feature_names].values
    y = df[target_col].values
    
    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Create sequences
    X_seq, y_seq = prepare_sequences(X_scaled, y, seq_len)
    
    # Split train/val (simple time-based split)
    split_idx = int(len(X_seq) * 0.8)
    X_train, X_val = X_seq[:split_idx], X_seq[split_idx:]
    y_train, y_val = y_seq[:split_idx], y_seq[split_idx:]
    
    logger.info(f"Training samples: {len(X_train)}, Validation samples: {len(X_val)}")
    
    # Initialize model
    model = LSTMQuantileRegressor(
        quantiles=quantiles,
        hidden_dim=config.get("hidden_dim", 64),
        num_layers=config.get("num_layers", 1),
        learning_rate=config.get("learning_rate", 0.001),
        batch_size=config.get("batch_size", 32),
        epochs=config.get("epochs", 50),
        device=config.get("device", "cpu")
    )
    
    # Train
    start_time = time.time()
    model.fit(X_train, y_train)
    duration = time.time() - start_time
    logger.info(f"Training completed in {duration:.2f}s")
    
    # Evaluate
    preds_val = model.predict(X_val)
    
    # Calculate validation metrics
    metrics = {}
    for q_key, preds in preds_val.items():
        q = float(q_key[1:])
        errors = y_val - preds
        loss = np.maximum((q - 1) * errors, q * errors).mean()
        metrics[f"loss_{q_key}"] = float(loss)
        
    logger.info(f"Validation Metrics: {json.dumps(metrics, indent=2)}")
    
    # Save model
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "model.pt"
    model.save(model_path)
    
    # Save scaler
    import joblib
    joblib.dump(scaler, output_dir / "scaler.joblib")
    
    # Save metrics
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

def main():
    parser = argparse.ArgumentParser(description="Train LSTM Quantile Model")
    parser.add_argument("--config", required=True, help="Path to config file")
    parser.add_argument("--dataset", required=True, help="Path to dataset CSV")
    parser.add_argument("--output", required=True, help="Output directory")
    
    args = parser.parse_args()
    
    config = load_config(args.config)
    df, feature_names = load_dataset(args.dataset)
    
    train_model(config, df, feature_names, Path(args.output))

if __name__ == "__main__":
    main()
