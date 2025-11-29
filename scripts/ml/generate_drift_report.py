#!/usr/bin/env python3
"""
Generate Drift Report.

Calculates data drift (PSI) and concept drift (MAE/RMSE) for a given index.
Compares 'reference' (training) data against 'current' (production) data.

Usage:
    python scripts/ml/generate_drift_report.py \
        --index NIFTY \
        --reference data/ml/training/nifty_tp_features_real.csv \
        --current data/ml/production/nifty_today.csv \
        --model models/nifty_gbrt_quantile/ \
        --output reports/drift/nifty_drift_report.md
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analytics.ml.drift import DriftMonitor
from src.analytics.ml.quantile import QuantileRegressor
from src.analytics.ml.feature_engineering import FeatureEngineer
from src.utils.logging_utils import setup_logging

setup_logging(terminal_level='INFO')
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Generate Drift Report")
    parser.add_argument("--index", required=True, help="Index name (e.g., NIFTY)")
    parser.add_argument("--reference", required=True, help="Path to reference (training) CSV")
    parser.add_argument("--current", required=True, help="Path to current (production) CSV")
    parser.add_argument("--model", required=True, help="Path to model directory")
    parser.add_argument("--output", help="Path to output report file (Markdown)")
    return parser.parse_args()


def main():
    args = parse_args()
    
    try:
        # 1. Load Data
        logger.info(f"Loading reference data: {args.reference}")
        ref_df = pd.read_csv(args.reference)
        
        logger.info(f"Loading current data: {args.current}")
        curr_df = pd.read_csv(args.current)
        
        if len(curr_df) == 0:
            logger.error("Current dataset is empty")
            sys.exit(1)
            
        # 2. Load Model and Feature Config
        logger.info(f"Loading model from: {args.model}")
        model = QuantileRegressor.load(args.model)
        
        # Load feature config
        model_dir = Path(args.model).parent
        feature_config_path = model_dir / "feature_engineering.json"
        
        if feature_config_path.exists():
            import json
            with open(feature_config_path, "r") as f:
                feature_config = json.load(f)
                features = feature_config.get("feature_names", [])
            logger.info(f"Loaded {len(features)} features from config")
        else:
            logger.warning("Feature config not found, using all common features")
            fe = FeatureEngineer()
            features = fe.get_feature_names()
            # Filter features present in both dfs
            features = [f for f in features if f in ref_df.columns and f in curr_df.columns]
        
        # 3. Initialize Monitor
        monitor = DriftMonitor()
        
        # 4. Check Data Drift (PSI)
        logger.info(f"Checking data drift for {len(features)} features...")
        
        # Ensure all features exist in dataframes
        missing_ref = [f for f in features if f not in ref_df.columns]
        missing_curr = [f for f in features if f not in curr_df.columns]
        
        if missing_ref or missing_curr:
            logger.error(f"Missing features in reference: {missing_ref}")
            logger.error(f"Missing features in current: {missing_curr}")
            sys.exit(1)
            
        data_drift = monitor.check_data_drift(ref_df, curr_df, features)
        
        # Identify high drift features (PSI > 0.2 is usually considered significant)
        high_drift = {k: v for k, v in data_drift.items() if v > 0.2}
        if high_drift:
            logger.warning(f"Found {len(high_drift)} features with high drift (PSI > 0.2)")
        
        # 5. Check Concept Drift (Model Performance)
        # We need to generate predictions for the current data to compare with actuals
        logger.info("Generating predictions for concept drift analysis...")
        
        # Prepare features for current data
        X_curr = curr_df[features].fillna(0).values
        
        # Predict P50 (median)
        preds = model.predict(X_curr)
        y_pred = preds.get("q0.50", np.zeros(len(curr_df)))
        
        # Get actuals (target)
        # The target column name depends on training config, usually 'tp_residual'
        target_col = "tp_residual"
        if target_col not in curr_df.columns:
            logger.warning(f"Target column '{target_col}' not found in current data. Skipping concept drift.")
            concept_drift = {}
        else:
            # Filter out NaNs from both y_true and y_pred
            y_true = curr_df[target_col].values
            
            valid_mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
            if np.sum(valid_mask) < len(y_true):
                logger.warning(f"Dropped {len(y_true) - np.sum(valid_mask)} rows with NaN values for concept drift")
                
            y_true_clean = y_true[valid_mask]
            y_pred_clean = y_pred[valid_mask]
            
            if len(y_true_clean) > 0:
                concept_drift = monitor.check_concept_drift(y_true_clean, y_pred_clean)
                logger.info(f"Concept Drift Metrics: {concept_drift}")
            else:
                logger.warning("No valid samples for concept drift analysis")
                concept_drift = {}
            
        # 6. Save Record
        monitor.save_drift_record(
            index=args.index,
            timestamp=time.time(),
            data_drift=data_drift,
            concept_drift=concept_drift,
            metadata={
                "reference_file": args.reference,
                "current_file": args.current,
                "model_path": args.model,
                "sample_size_ref": len(ref_df),
                "sample_size_curr": len(curr_df)
            }
        )
        
        # 7. Get Long-Term Accuracy
        long_term_stats = monitor.get_long_term_accuracy(args.index)
        
        # 8. Generate Report
        if args.output:
            generate_markdown_report(args.output, args.index, data_drift, concept_drift, high_drift, long_term_stats)
            
    except Exception as e:
        logger.error(f"Drift analysis failed: {e}", exc_info=True)
        sys.exit(1)


def generate_markdown_report(
    output_path: str,
    index: str,
    data_drift: Dict[str, float],
    concept_drift: Dict[str, float],
    high_drift: Dict[str, float],
    long_term_stats: Dict[str, float]
):
    """Generate a Markdown report."""
    # Ensure directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# Drift Report: {index}\n\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## 1. Concept Drift (Model Performance)\n")
        if concept_drift:
            f.write("| Metric | Value |\n")
            f.write("|---|---|\n")
            for k, v in concept_drift.items():
                f.write(f"| {k.upper()} | {v:.4f} |\n")
        else:
            f.write("No concept drift metrics available (missing target column).\n")
        f.write("\n")
        
        f.write("## 2. Long-Term Accuracy Trends (Last 30 Checks)\n")
        if long_term_stats:
            f.write("| Metric | Value |\n")
            f.write("|---|---|\n")
            f.write(f"| Average MAE | {long_term_stats.get('avg_mae', 0):.4f} |\n")
            f.write(f"| Average MAPE | {long_term_stats.get('avg_mape', 0):.4f}% |\n")
            
            trend = long_term_stats.get('mae_trend', 0)
            trend_icon = "➡️"
            if trend > 0.1: trend_icon = "jq (Degrading)"
            elif trend < -0.1: trend_icon = "↘️ (Improving)"
            
            f.write(f"| MAE Trend | {trend:.4f} {trend_icon} |\n")
            f.write(f"| Samples | {int(long_term_stats.get('samples_count', 0))} |\n")
        else:
            f.write("No history available yet.\n")
        f.write("\n")
        
        f.write("## 3. Data Drift (Feature Distribution)\n")
        f.write(f"Total features checked: {len(data_drift)}\n\n")
        
        if high_drift:
            f.write("### ⚠️ High Drift Features (PSI > 0.2)\n")
            f.write("| Feature | PSI |\n")
            f.write("|---|---|\n")
            for k, v in sorted(high_drift.items(), key=lambda x: x[1], reverse=True):
                f.write(f"| {k} | {v:.4f} |\n")
        else:
            f.write("✅ No features showed significant drift (PSI < 0.2).\n")
            
        f.write("\n### All Features PSI\n")
        f.write("| Feature | PSI |\n")
        f.write("|---|---|\n")
        for k, v in sorted(data_drift.items(), key=lambda x: x[1], reverse=True):
            f.write(f"| {k} | {v:.4f} |\n")
            
    logger.info(f"Report saved to {output_path}")


if __name__ == "__main__":
    main()
