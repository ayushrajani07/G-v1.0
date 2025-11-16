#!/usr/bin/env python3
"""
Model Drift Detection Script (Phase 5)

Detect model performance drift and feature distribution shifts.

Drift Indicators:
- MAE degradation > 15%
- Coverage drift > 5%
- Feature distribution shifts (KL divergence, KS test)
- Residual bias changes

Based on ML_ARM_IMPLEMENTATION_ROADMAP.md Phase 5 specifications.

Usage:
    python scripts/ml/detect_model_drift.py \
        --index NIFTY \
        --baseline-period 30d \
        --test-period 7d \
        --alert-threshold 0.15 \
        --output reports/drift_detection.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy import stats

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def calculate_performance_metrics(
    df: pd.DataFrame,
    actual_col: str = "tp_actual",
    pred_col: str = "pred_p50",
    pred_p10_col: str = "pred_p10",
    pred_p90_col: str = "pred_p90"
) -> Dict[str, float]:
    """Calculate performance metrics for a period.
    
    Args:
        df: DataFrame with predictions and actuals
        actual_col: Name of actual values column
        pred_col: Name of prediction column
        pred_p10_col: Name of P10 prediction column
        pred_p90_col: Name of P90 prediction column
        
    Returns:
        Dictionary of performance metrics
    """
    actuals = df[actual_col].values
    preds = df[pred_col].values
    preds_p10 = df[pred_p10_col].values if pred_p10_col in df.columns else None
    preds_p90 = df[pred_p90_col].values if pred_p90_col in df.columns else None
    
    # Filter valid samples
    valid_mask = ~(np.isnan(actuals) | np.isnan(preds))
    actuals = actuals[valid_mask]
    preds = preds[valid_mask]
    
    if preds_p10 is not None:
        preds_p10 = preds_p10[valid_mask]
    if preds_p90 is not None:
        preds_p90 = preds_p90[valid_mask]
    
    if len(actuals) == 0:
        logger.warning("No valid samples for metric calculation")
        return {
            "n_samples": 0,
            "mae": np.nan,
            "rmse": np.nan,
            "bias": np.nan,
            "coverage": np.nan
        }
    
    # Calculate metrics
    errors = actuals - preds
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    bias = float(np.mean(errors))
    
    # Coverage
    coverage = np.nan
    if preds_p10 is not None and preds_p90 is not None:
        within_band = (actuals >= preds_p10) & (actuals <= preds_p90)
        coverage = float(np.mean(within_band) * 100)
    
    return {
        "n_samples": int(len(actuals)),
        "mae": mae,
        "rmse": rmse,
        "bias": bias,
        "coverage": coverage
    }


def detect_performance_drift(
    baseline_metrics: Dict[str, float],
    test_metrics: Dict[str, float],
    alert_threshold: float = 0.15
) -> Dict[str, Any]:
    """Detect performance drift between baseline and test periods.
    
    Args:
        baseline_metrics: Baseline period metrics
        test_metrics: Test period metrics
        alert_threshold: Threshold for drift alert (default: 0.15 = 15%)
        
    Returns:
        Drift detection results
    """
    logger.info("Detecting performance drift")
    
    drift_detected = False
    drift_details = {}
    
    # MAE drift
    if not np.isnan(baseline_metrics["mae"]) and not np.isnan(test_metrics["mae"]):
        mae_change = (test_metrics["mae"] - baseline_metrics["mae"]) / baseline_metrics["mae"]
        drift_details["mae_change_pct"] = float(mae_change * 100)
        
        if mae_change > alert_threshold:
            drift_detected = True
            logger.warning(f"MAE degradation detected: {mae_change*100:.2f}%")
    
    # RMSE drift
    if not np.isnan(baseline_metrics["rmse"]) and not np.isnan(test_metrics["rmse"]):
        rmse_change = (test_metrics["rmse"] - baseline_metrics["rmse"]) / baseline_metrics["rmse"]
        drift_details["rmse_change_pct"] = float(rmse_change * 100)
    
    # Bias drift
    if not np.isnan(baseline_metrics["bias"]) and not np.isnan(test_metrics["bias"]):
        bias_change = test_metrics["bias"] - baseline_metrics["bias"]
        drift_details["bias_change_abs"] = float(bias_change)
        
        # Alert if bias changes significantly
        if abs(bias_change) > baseline_metrics["mae"] * 0.5:
            drift_detected = True
            logger.warning(f"Significant bias shift detected: {bias_change:.4f}")
    
    # Coverage drift
    if not np.isnan(baseline_metrics["coverage"]) and not np.isnan(test_metrics["coverage"]):
        coverage_change = test_metrics["coverage"] - baseline_metrics["coverage"]
        drift_details["coverage_change_pct"] = float(coverage_change)
        
        if abs(coverage_change) > 5.0:
            drift_detected = True
            logger.warning(f"Coverage drift detected: {coverage_change:.2f}%")
    
    return {
        "drift_detected": drift_detected,
        "drift_details": drift_details
    }


def compute_feature_distribution_drift(
    baseline_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_cols: List[str]
) -> Dict[str, Dict[str, float]]:
    """Compute feature distribution drift using KS test and KL divergence.
    
    Args:
        baseline_df: Baseline period data
        test_df: Test period data
        feature_cols: List of feature columns to check
        
    Returns:
        Dictionary mapping feature names to drift metrics
    """
    logger.info("Computing feature distribution drift")
    
    drift_by_feature = {}
    
    for feature in feature_cols:
        if feature not in baseline_df.columns or feature not in test_df.columns:
            continue
        
        baseline_values = baseline_df[feature].dropna().values
        test_values = test_df[feature].dropna().values
        
        if len(baseline_values) < 10 or len(test_values) < 10:
            continue
        
        try:
            # Kolmogorov-Smirnov test
            ks_stat, ks_pvalue = stats.ks_2samp(baseline_values, test_values)
            
            # Calculate KL divergence (approximate using histograms)
            # Determine bins based on combined data range
            combined_min = min(baseline_values.min(), test_values.min())
            combined_max = max(baseline_values.max(), test_values.max())
            bins = np.linspace(combined_min, combined_max, 20)
            
            hist_baseline, _ = np.histogram(baseline_values, bins=bins, density=True)
            hist_test, _ = np.histogram(test_values, bins=bins, density=True)
            
            # Add small epsilon to avoid log(0)
            epsilon = 1e-10
            hist_baseline = hist_baseline + epsilon
            hist_test = hist_test + epsilon
            
            # Normalize
            hist_baseline = hist_baseline / hist_baseline.sum()
            hist_test = hist_test / hist_test.sum()
            
            # KL divergence
            kl_div = float(np.sum(hist_test * np.log(hist_test / hist_baseline)))
            
            drift_by_feature[feature] = {
                "ks_statistic": float(ks_stat),
                "ks_pvalue": float(ks_pvalue),
                "kl_divergence": kl_div,
                "significant_drift": ks_pvalue < 0.05
            }
            
            if ks_pvalue < 0.05:
                logger.info(f"Significant distribution drift in feature: {feature} (p={ks_pvalue:.4f})")
        
        except Exception as e:
            logger.warning(f"Failed to compute drift for feature {feature}: {e}")
    
    return drift_by_feature


def load_period_data(
    data_path: Path,
    period_str: str
) -> Tuple[pd.DataFrame, datetime, datetime]:
    """Load data for a specific period.
    
    Args:
        data_path: Path to data CSV
        period_str: Period string (e.g., "30d", "7d")
        
    Returns:
        Tuple of (dataframe, start_date, end_date)
    """
    logger.info(f"Loading data from {data_path}")
    
    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")
    
    df = pd.read_csv(data_path)
    
    # Parse period
    if period_str.endswith("d"):
        days = int(period_str[:-1])
    elif period_str.endswith("w"):
        days = int(period_str[:-1]) * 7
    else:
        raise ValueError(f"Invalid period format: {period_str}")
    
    # Filter by timestamp if available
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        end_date = df["timestamp"].max()
        start_date = end_date - timedelta(days=days)
        df = df[(df["timestamp"] >= start_date) & (df["timestamp"] <= end_date)]
    else:
        # Use most recent N samples
        df = df.tail(days * 375)  # Approximate: 375 minutes per day
        start_date = datetime.now() - timedelta(days=days)
        end_date = datetime.now()
    
    logger.info(f"Loaded {len(df)} samples for period {period_str}")
    return df, start_date, end_date


def generate_report(
    baseline_metrics: Dict[str, float],
    test_metrics: Dict[str, float],
    performance_drift: Dict[str, Any],
    feature_drift: Dict[str, Dict[str, float]],
    config: Dict[str, Any],
    output_path: Path
) -> None:
    """Generate drift detection report.
    
    Args:
        baseline_metrics: Baseline period metrics
        test_metrics: Test period metrics
        performance_drift: Performance drift results
        feature_drift: Feature distribution drift results
        config: Configuration dictionary
        output_path: Output path for report
    """
    # Count features with significant drift
    n_drifted_features = sum(
        1 for metrics in feature_drift.values()
        if metrics.get("significant_drift", False)
    )
    
    report = {
        "detection_info": {
            "timestamp": datetime.now().isoformat(),
            "index": config.get("index", "NIFTY"),
            "baseline_period": config.get("baseline_period", "30d"),
            "test_period": config.get("test_period", "7d"),
            "alert_threshold": config.get("alert_threshold", 0.15)
        },
        "baseline_metrics": baseline_metrics,
        "test_metrics": test_metrics,
        "performance_drift": performance_drift,
        "feature_drift": {
            "n_features_checked": len(feature_drift),
            "n_features_drifted": n_drifted_features,
            "details": feature_drift
        },
        "summary": {
            "drift_detected": performance_drift.get("drift_detected", False),
            "severity": "none",
            "recommendations": []
        }
    }
    
    # Determine severity and recommendations
    drift_detected = performance_drift.get("drift_detected", False)
    drift_details = performance_drift.get("drift_details", {})
    
    if drift_detected:
        mae_change = drift_details.get("mae_change_pct", 0)
        
        if mae_change > 30:
            report["summary"]["severity"] = "critical"
            report["summary"]["recommendations"].append(
                "URGENT: Critical performance degradation detected. "
                "Immediate model retraining recommended."
            )
        elif mae_change > 15:
            report["summary"]["severity"] = "high"
            report["summary"]["recommendations"].append(
                "Significant performance degradation detected. "
                "Schedule model retraining within 24 hours."
            )
        else:
            report["summary"]["severity"] = "medium"
            report["summary"]["recommendations"].append(
                "Moderate performance drift detected. "
                "Monitor closely and consider retraining."
            )
    
    # Check feature drift
    if n_drifted_features > len(feature_drift) * 0.3:
        report["summary"]["recommendations"].append(
            f"Many features showing distribution shift ({n_drifted_features}/{len(feature_drift)}). "
            f"Market regime may have changed."
        )
    
    # Coverage recommendations
    coverage_change = drift_details.get("coverage_change_pct", 0)
    if abs(coverage_change) > 5:
        report["summary"]["recommendations"].append(
            f"Coverage drift detected ({coverage_change:+.1f}%). "
            f"Consider recalibrating conformal prediction."
        )
    
    # Save report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"Report saved to {output_path}")
    
    # Print summary to console
    print("\n" + "="*80)
    print("MODEL DRIFT DETECTION RESULTS")
    print("="*80)
    
    print("\nBaseline Metrics:")
    for key, value in baseline_metrics.items():
        if isinstance(value, (int, float)):
            print(f"  {key:20s}: {value:.4f}")
    
    print("\nTest Metrics:")
    for key, value in test_metrics.items():
        if isinstance(value, (int, float)):
            print(f"  {key:20s}: {value:.4f}")
    
    print("\nPerformance Drift:")
    for key, value in drift_details.items():
        print(f"  {key:30s}: {value:.4f}")
    
    print("\nFeature Distribution Drift:")
    print(f"  Features checked: {len(feature_drift)}")
    print(f"  Features with significant drift: {n_drifted_features}")
    
    print("\nSummary:")
    print(f"  Drift detected: {drift_detected}")
    print(f"  Severity: {report['summary']['severity']}")
    
    if report['summary']['recommendations']:
        print("\n  Recommendations:")
        for rec in report['summary']['recommendations']:
            print(f"    - {rec}")
    
    print("="*80 + "\n")


def main() -> int:
    """Main entry point for drift detection."""
    parser = argparse.ArgumentParser(
        description="Detect model performance drift and feature distribution shifts"
    )
    parser.add_argument(
        "--index",
        type=str,
        default="NIFTY",
        help="Index to check (NIFTY, BANKNIFTY)"
    )
    parser.add_argument(
        "--baseline-period",
        type=str,
        default="30d",
        help="Baseline period (e.g., 30d, 4w)"
    )
    parser.add_argument(
        "--test-period",
        type=str,
        default="7d",
        help="Test period (e.g., 7d, 1w)"
    )
    parser.add_argument(
        "--alert-threshold",
        type=float,
        default=0.15,
        help="MAE degradation threshold for alert (default: 0.15 = 15%)"
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        help="Path to evaluation data CSV"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/drift_detection.json"),
        help="Output path for drift report"
    )
    parser.add_argument(
        "--check-features",
        action="store_true",
        help="Also check feature distribution drift (requires feature columns)"
    )
    
    args = parser.parse_args()
    
    # Setup configuration
    config = {
        "index": args.index,
        "baseline_period": args.baseline_period,
        "test_period": args.test_period,
        "alert_threshold": args.alert_threshold
    }
    
    # Determine data path if not provided
    if args.data_path is None:
        args.data_path = Path(f"data/ml/evaluation/{args.index.lower()}_evaluation_data.csv")
    
    try:
        # Load baseline period data
        logger.info(f"Loading baseline period: {args.baseline_period}")
        baseline_df, baseline_start, baseline_end = load_period_data(
            args.data_path,
            args.baseline_period
        )
        
        # Calculate baseline metrics
        baseline_metrics = calculate_performance_metrics(baseline_df)
        
        # Load test period data
        logger.info(f"Loading test period: {args.test_period}")
        test_df, test_start, test_end = load_period_data(
            args.data_path,
            args.test_period
        )
        
        # Calculate test metrics
        test_metrics = calculate_performance_metrics(test_df)
        
        # Detect performance drift
        performance_drift = detect_performance_drift(
            baseline_metrics,
            test_metrics,
            args.alert_threshold
        )
        
        # Check feature drift if requested
        feature_drift = {}
        if args.check_features:
            # Get feature columns (columns starting with standard feature prefixes)
            feature_cols = [
                col for col in baseline_df.columns
                if any(col.startswith(prefix) for prefix in [
                    "residual_lag_", "residual_roll_mean_", "residual_roll_std_",
                    "index_return_", "iv_", "minutes_to_expiry", "time_"
                ])
            ]
            
            if feature_cols:
                logger.info(f"Checking distribution drift for {len(feature_cols)} features")
                feature_drift = compute_feature_distribution_drift(
                    baseline_df,
                    test_df,
                    feature_cols
                )
            else:
                logger.warning("No feature columns found for drift analysis")
        
        # Generate report
        generate_report(
            baseline_metrics,
            test_metrics,
            performance_drift,
            feature_drift,
            config,
            args.output
        )
        
        # Return exit code based on drift detection
        if performance_drift.get("drift_detected", False):
            logger.warning("Drift detected - returning exit code 1")
            return 1
        
        logger.info("No significant drift detected")
        return 0
        
    except Exception as e:
        logger.error(f"Drift detection failed: {e}", exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
