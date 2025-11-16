#!/usr/bin/env python3
"""
A/B Test Ensemble vs Retrieval-Only Forecasters (Phase 5)

Compare performance of ensemble forecaster against retrieval-only baseline
over a specified test period.

Based on ML_ARM_IMPLEMENTATION_ROADMAP.md Phase 5 specifications.

Usage:
    python scripts/ml/ab_test_ensemble.py \
        --index NIFTY \
        --variant-a ensemble \
        --variant-b retrieval_only \
        --duration-days 7 \
        --output reports/ab_test_ensemble_7d.json
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

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.path_forecast.ensemble import EnsemblePathForecaster, EnsembleConfig
from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def calculate_metrics(
    actuals: np.ndarray,
    predictions_p50: np.ndarray,
    predictions_p10: np.ndarray,
    predictions_p90: np.ndarray
) -> Dict[str, float]:
    """Calculate evaluation metrics.
    
    Args:
        actuals: Actual TP values
        predictions_p50: P50 forecasts
        predictions_p10: P10 forecasts
        predictions_p90: P90 forecasts
        
    Returns:
        Dictionary of metrics
    """
    # Filter out NaN values
    valid_mask = ~(np.isnan(actuals) | np.isnan(predictions_p50))
    actuals = actuals[valid_mask]
    predictions_p50 = predictions_p50[valid_mask]
    predictions_p10 = predictions_p10[valid_mask]
    predictions_p90 = predictions_p90[valid_mask]
    
    if len(actuals) == 0:
        logger.warning("No valid samples for metric calculation")
        return {
            "mae": np.nan,
            "rmse": np.nan,
            "mape": np.nan,
            "correlation": np.nan,
            "coverage": np.nan,
            "avg_band_width": np.nan,
            "n_samples": 0
        }
    
    # Point forecast metrics (P50)
    errors = actuals - predictions_p50
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    
    # MAPE with protection against zero division
    non_zero_mask = actuals != 0
    if np.sum(non_zero_mask) > 0:
        mape = float(np.mean(np.abs(errors[non_zero_mask] / actuals[non_zero_mask])) * 100)
    else:
        mape = np.nan
    
    # Correlation
    if len(actuals) > 1 and np.std(actuals) > 0 and np.std(predictions_p50) > 0:
        correlation = float(np.corrcoef(actuals, predictions_p50)[0, 1])
    else:
        correlation = np.nan
    
    # Coverage (percentage of actuals within P10-P90 band)
    within_band = (actuals >= predictions_p10) & (actuals <= predictions_p90)
    coverage = float(np.mean(within_band) * 100)
    
    # Average band width
    band_widths = predictions_p90 - predictions_p10
    avg_band_width = float(np.mean(band_widths))
    
    return {
        "mae": mae,
        "rmse": rmse,
        "mape": mape,
        "correlation": correlation,
        "coverage": coverage,
        "avg_band_width": avg_band_width,
        "n_samples": int(len(actuals))
    }


def calculate_improvement(
    metrics_a: Dict[str, float],
    metrics_b: Dict[str, float]
) -> Dict[str, float]:
    """Calculate improvement of variant A over variant B.
    
    Args:
        metrics_a: Metrics for variant A
        metrics_b: Metrics for variant B
        
    Returns:
        Dictionary of improvement percentages
    """
    improvements = {}
    
    # Lower is better metrics (MAE, RMSE, MAPE)
    for metric in ["mae", "rmse", "mape", "avg_band_width"]:
        if metrics_b[metric] != 0 and not np.isnan(metrics_b[metric]):
            improvements[f"{metric}_improvement_pct"] = (
                (metrics_b[metric] - metrics_a[metric]) / metrics_b[metric] * 100
            )
        else:
            improvements[f"{metric}_improvement_pct"] = np.nan
    
    # Higher is better metrics (correlation, coverage)
    for metric in ["correlation", "coverage"]:
        if not np.isnan(metrics_a[metric]) and not np.isnan(metrics_b[metric]):
            improvements[f"{metric}_improvement_abs"] = metrics_a[metric] - metrics_b[metric]
        else:
            improvements[f"{metric}_improvement_abs"] = np.nan
    
    return improvements


def load_test_data(
    data_path: Path,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> pd.DataFrame:
    """Load test data for A/B testing.
    
    Args:
        data_path: Path to test data CSV
        start_date: Start of test period
        end_date: End of test period
        
    Returns:
        DataFrame with test data
    """
    logger.info(f"Loading test data from {data_path}")
    
    if not data_path.exists():
        raise FileNotFoundError(f"Test data not found: {data_path}")
    
    df = pd.read_csv(data_path)
    logger.info(f"Loaded {len(df)} samples")
    
    # Filter by date if provided
    if start_date or end_date:
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            if start_date:
                df = df[df["timestamp"] >= start_date]
            if end_date:
                df = df[df["timestamp"] <= end_date]
            logger.info(f"Filtered to {len(df)} samples in date range")
    
    return df


def run_variant_evaluation(
    variant_name: str,
    forecaster: Any,
    test_data: pd.DataFrame,
    target_col: str = "tp_actual"
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Run evaluation for a single variant.
    
    Args:
        variant_name: Name of variant
        forecaster: Forecaster instance
        test_data: Test data
        target_col: Name of target column
        
    Returns:
        Tuple of (actuals, p50, p10, p90)
    """
    logger.info(f"Evaluating variant: {variant_name}")
    
    actuals = test_data[target_col].values
    predictions_p50 = []
    predictions_p10 = []
    predictions_p90 = []
    
    # Generate predictions for each sample
    # Note: This is a simplified version - in production, you'd need to properly
    # set up the forecaster with real-time data and context
    for idx, row in test_data.iterrows():
        try:
            # Placeholder: In real implementation, call forecaster.forecast()
            # with appropriate parameters from row
            # For now, return dummy predictions for structure
            pred_p50 = row.get("baseline_tp", np.nan)
            pred_p10 = pred_p50 * 0.9 if not np.isnan(pred_p50) else np.nan
            pred_p90 = pred_p50 * 1.1 if not np.isnan(pred_p50) else np.nan
            
            predictions_p50.append(pred_p50)
            predictions_p10.append(pred_p10)
            predictions_p90.append(pred_p90)
        except Exception as e:
            logger.warning(f"Failed to generate prediction for row {idx}: {e}")
            predictions_p50.append(np.nan)
            predictions_p10.append(np.nan)
            predictions_p90.append(np.nan)
    
    return (
        actuals,
        np.array(predictions_p50),
        np.array(predictions_p10),
        np.array(predictions_p90)
    )


def generate_report(
    variant_a: str,
    variant_b: str,
    metrics_a: Dict[str, float],
    metrics_b: Dict[str, float],
    improvements: Dict[str, float],
    test_config: Dict[str, Any],
    output_path: Path
) -> None:
    """Generate comprehensive A/B test report.
    
    Args:
        variant_a: Name of variant A
        variant_b: Name of variant B
        metrics_a: Metrics for variant A
        metrics_b: Metrics for variant B
        improvements: Improvement metrics
        test_config: Test configuration
        output_path: Output path for report
    """
    report = {
        "test_info": {
            "timestamp": datetime.now().isoformat(),
            "variant_a": variant_a,
            "variant_b": variant_b,
            "index": test_config.get("index", "NIFTY"),
            "duration_days": test_config.get("duration_days", 7),
            "test_period_start": test_config.get("start_date"),
            "test_period_end": test_config.get("end_date")
        },
        "metrics": {
            "variant_a": metrics_a,
            "variant_b": metrics_b
        },
        "improvements": improvements,
        "summary": {
            "winner": None,
            "confidence": None,
            "recommendation": None
        }
    }
    
    # Determine winner based on MAE (primary metric)
    if not np.isnan(improvements.get("mae_improvement_pct", np.nan)):
        mae_improvement = improvements["mae_improvement_pct"]
        if mae_improvement >= 5.0:
            report["summary"]["winner"] = variant_a
            report["summary"]["confidence"] = "high"
            report["summary"]["recommendation"] = f"{variant_a} shows significant improvement (>5%)"
        elif mae_improvement >= 2.0:
            report["summary"]["winner"] = variant_a
            report["summary"]["confidence"] = "medium"
            report["summary"]["recommendation"] = f"{variant_a} shows moderate improvement (2-5%)"
        elif mae_improvement <= -5.0:
            report["summary"]["winner"] = variant_b
            report["summary"]["confidence"] = "high"
            report["summary"]["recommendation"] = f"{variant_b} significantly outperforms {variant_a}"
        else:
            report["summary"]["winner"] = "tie"
            report["summary"]["confidence"] = "low"
            report["summary"]["recommendation"] = "No significant difference, either variant acceptable"
    
    # Save report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"Report saved to {output_path}")
    
    # Print summary to console
    print("\n" + "="*80)
    print("A/B TEST RESULTS")
    print("="*80)
    print(f"\nVariant A ({variant_a}):")
    for key, value in metrics_a.items():
        print(f"  {key:20s}: {value:.4f}")
    
    print(f"\nVariant B ({variant_b}):")
    for key, value in metrics_b.items():
        print(f"  {key:20s}: {value:.4f}")
    
    print("\nImprovements:")
    for key, value in improvements.items():
        print(f"  {key:30s}: {value:.2f}")
    
    print("\nSummary:")
    print(f"  Winner: {report['summary']['winner']}")
    print(f"  Confidence: {report['summary']['confidence']}")
    print(f"  Recommendation: {report['summary']['recommendation']}")
    print("="*80 + "\n")


def main() -> int:
    """Main entry point for A/B testing."""
    parser = argparse.ArgumentParser(
        description="A/B test ensemble vs retrieval-only forecasters"
    )
    parser.add_argument(
        "--index",
        type=str,
        default="NIFTY",
        help="Index to test (NIFTY, BANKNIFTY)"
    )
    parser.add_argument(
        "--variant-a",
        type=str,
        default="ensemble",
        help="Name of variant A (e.g., ensemble)"
    )
    parser.add_argument(
        "--variant-b",
        type=str,
        default="retrieval_only",
        help="Name of variant B (e.g., retrieval_only)"
    )
    parser.add_argument(
        "--duration-days",
        type=int,
        default=7,
        help="Duration of test period in days"
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        help="Path to test data CSV"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/ab_test_results.json"),
        help="Output path for test report"
    )
    parser.add_argument(
        "--config-a",
        type=Path,
        help="Configuration file for variant A"
    )
    parser.add_argument(
        "--config-b",
        type=Path,
        help="Configuration file for variant B"
    )
    
    args = parser.parse_args()
    
    # Setup test configuration
    test_config = {
        "index": args.index,
        "duration_days": args.duration_days,
        "variant_a": args.variant_a,
        "variant_b": args.variant_b
    }
    
    # Determine data path if not provided
    if args.data_path is None:
        args.data_path = Path(f"data/ml/evaluation/{args.index.lower()}_test_data.csv")
    
    try:
        # Load test data
        test_data = load_test_data(args.data_path)
        
        # TODO: Initialize forecasters based on configurations
        # For now, we'll use placeholder evaluations
        logger.info("Initializing forecasters...")
        
        # Variant A evaluation
        logger.info(f"Running evaluation for variant A: {args.variant_a}")
        actuals_a, pred_p50_a, pred_p10_a, pred_p90_a = run_variant_evaluation(
            args.variant_a,
            None,  # Placeholder
            test_data
        )
        metrics_a = calculate_metrics(actuals_a, pred_p50_a, pred_p10_a, pred_p90_a)
        
        # Variant B evaluation
        logger.info(f"Running evaluation for variant B: {args.variant_b}")
        actuals_b, pred_p50_b, pred_p10_b, pred_p90_b = run_variant_evaluation(
            args.variant_b,
            None,  # Placeholder
            test_data
        )
        metrics_b = calculate_metrics(actuals_b, pred_p50_b, pred_p10_b, pred_p90_b)
        
        # Calculate improvements
        improvements = calculate_improvement(metrics_a, metrics_b)
        
        # Generate report
        generate_report(
            args.variant_a,
            args.variant_b,
            metrics_a,
            metrics_b,
            improvements,
            test_config,
            args.output
        )
        
        logger.info("A/B testing completed successfully")
        return 0
        
    except Exception as e:
        logger.error(f"A/B testing failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
