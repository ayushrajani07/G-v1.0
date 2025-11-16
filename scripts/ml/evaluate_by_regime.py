#!/usr/bin/env python3
"""
Regime-Specific Evaluation Script (Phase 5)

Evaluate forecaster performance across different market regimes:
- High Volatility: IV > 80th percentile
- Low Volatility: IV < 20th percentile
- Trending: Directional move > 1% per hour
- Sideways: Directional move < 0.3% per hour

Based on ML_ARM_IMPLEMENTATION_ROADMAP.md Phase 5 specifications.

Usage:
    python scripts/ml/evaluate_by_regime.py \
        --index NIFTY \
        --days 30 \
        --regimes high_vol,low_vol,trending,sideways \
        --output reports/regime_evaluation_30d.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timedelta
from enum import Enum

import numpy as np
import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MarketRegime(str, Enum):
    """Market regime classifications."""
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    TRENDING = "trending"
    SIDEWAYS = "sideways"
    UNKNOWN = "unknown"


def classify_regime(
    row: pd.Series,
    iv_high_threshold: float,
    iv_low_threshold: float,
    trend_threshold: float = 1.0,
    sideways_threshold: float = 0.3
) -> MarketRegime:
    """Classify market regime for a single row.
    
    Args:
        row: DataFrame row with market data
        iv_high_threshold: IV threshold for high volatility (e.g., 80th percentile)
        iv_low_threshold: IV threshold for low volatility (e.g., 20th percentile)
        trend_threshold: Price change % threshold for trending (default: 1%)
        sideways_threshold: Price change % threshold for sideways (default: 0.3%)
        
    Returns:
        MarketRegime classification
    """
    iv = row.get("avg_iv", np.nan)
    price_change_pct = row.get("price_change_1h_pct", np.nan)
    
    # Check volatility-based regimes first
    if not np.isnan(iv):
        if iv > iv_high_threshold:
            return MarketRegime.HIGH_VOL
        elif iv < iv_low_threshold:
            return MarketRegime.LOW_VOL
    
    # Check trend-based regimes
    if not np.isnan(price_change_pct):
        abs_change = abs(price_change_pct)
        if abs_change > trend_threshold:
            return MarketRegime.TRENDING
        elif abs_change < sideways_threshold:
            return MarketRegime.SIDEWAYS
    
    return MarketRegime.UNKNOWN


def compute_regime_thresholds(
    df: pd.DataFrame,
    iv_column: str = "avg_iv"
) -> Tuple[float, float]:
    """Compute IV thresholds for regime classification.
    
    Args:
        df: DataFrame with market data
        iv_column: Name of IV column
        
    Returns:
        Tuple of (iv_high_threshold, iv_low_threshold)
    """
    if iv_column not in df.columns:
        logger.warning(f"IV column '{iv_column}' not found, using defaults")
        return (0.3, 0.15)
    
    iv_values = df[iv_column].dropna()
    if len(iv_values) == 0:
        logger.warning("No valid IV values found, using defaults")
        return (0.3, 0.15)
    
    iv_high = float(np.percentile(iv_values, 80))
    iv_low = float(np.percentile(iv_values, 20))
    
    logger.info(f"IV thresholds: high={iv_high:.4f}, low={iv_low:.4f}")
    return (iv_high, iv_low)


def compute_price_change(
    df: pd.DataFrame,
    price_column: str = "index_price",
    window: int = 60
) -> pd.Series:
    """Compute rolling price change percentage.
    
    Args:
        df: DataFrame with price data
        price_column: Name of price column
        window: Window size in minutes (default: 60 for 1 hour)
        
    Returns:
        Series with price change percentages
    """
    if price_column not in df.columns:
        logger.warning(f"Price column '{price_column}' not found")
        return pd.Series(np.nan, index=df.index)
    
    prices = df[price_column]
    price_change_pct = ((prices - prices.shift(window)) / prices.shift(window) * 100)
    
    return price_change_pct


def calculate_regime_metrics(
    df: pd.DataFrame,
    regime_col: str = "regime"
) -> Dict[str, Dict[str, float]]:
    """Calculate evaluation metrics for each regime.
    
    Args:
        df: DataFrame with predictions and actuals
        regime_col: Name of regime column
        
    Returns:
        Dictionary mapping regime to metrics
    """
    metrics_by_regime = {}
    
    for regime in MarketRegime:
        if regime == MarketRegime.UNKNOWN:
            continue
        
        regime_data = df[df[regime_col] == regime.value]
        if len(regime_data) == 0:
            logger.info(f"No samples for regime: {regime.value}")
            continue
        
        # Extract predictions and actuals
        actuals = regime_data["tp_actual"].values
        pred_p50 = regime_data.get("pred_p50", pd.Series(np.nan, index=regime_data.index)).values
        pred_p10 = regime_data.get("pred_p10", pd.Series(np.nan, index=regime_data.index)).values
        pred_p90 = regime_data.get("pred_p90", pd.Series(np.nan, index=regime_data.index)).values
        
        # Filter valid samples
        valid_mask = ~(np.isnan(actuals) | np.isnan(pred_p50))
        n_valid = np.sum(valid_mask)
        
        if n_valid == 0:
            logger.warning(f"No valid samples for regime: {regime.value}")
            continue
        
        actuals = actuals[valid_mask]
        pred_p50 = pred_p50[valid_mask]
        pred_p10 = pred_p10[valid_mask]
        pred_p90 = pred_p90[valid_mask]
        
        # Calculate metrics
        errors = actuals - pred_p50
        mae = float(np.mean(np.abs(errors)))
        rmse = float(np.sqrt(np.mean(errors ** 2)))
        
        # MAPE
        non_zero_mask = actuals != 0
        if np.sum(non_zero_mask) > 0:
            mape = float(np.mean(np.abs(errors[non_zero_mask] / actuals[non_zero_mask])) * 100)
        else:
            mape = np.nan
        
        # Correlation
        if len(actuals) > 1 and np.std(actuals) > 0 and np.std(pred_p50) > 0:
            correlation = float(np.corrcoef(actuals, pred_p50)[0, 1])
        else:
            correlation = np.nan
        
        # Coverage
        within_band = (actuals >= pred_p10) & (actuals <= pred_p90)
        coverage = float(np.mean(within_band) * 100)
        
        # Band width
        band_widths = pred_p90 - pred_p10
        avg_band_width = float(np.mean(band_widths))
        
        metrics_by_regime[regime.value] = {
            "n_samples": int(n_valid),
            "mae": mae,
            "rmse": rmse,
            "mape": mape,
            "correlation": correlation,
            "coverage": coverage,
            "avg_band_width": avg_band_width
        }
        
        logger.info(f"Regime {regime.value}: n={n_valid}, MAE={mae:.4f}, Coverage={coverage:.2f}%")
    
    return metrics_by_regime


def perform_statistical_tests(
    df: pd.DataFrame,
    regime_col: str = "regime"
) -> Dict[str, Any]:
    """Perform statistical significance tests between regimes.
    
    Args:
        df: DataFrame with predictions and actuals
        regime_col: Name of regime column
        
    Returns:
        Dictionary with test results
    """
    from scipy import stats
    
    test_results = {}
    regimes = [r.value for r in MarketRegime if r != MarketRegime.UNKNOWN]
    
    # Compare each pair of regimes
    for i, regime_a in enumerate(regimes):
        for regime_b in regimes[i+1:]:
            data_a = df[df[regime_col] == regime_a]
            data_b = df[df[regime_col] == regime_b]
            
            if len(data_a) < 10 or len(data_b) < 10:
                continue
            
            # Get errors for each regime
            errors_a = (data_a["tp_actual"] - data_a.get("pred_p50", np.nan)).dropna().values
            errors_b = (data_b["tp_actual"] - data_b.get("pred_p50", np.nan)).dropna().values
            
            if len(errors_a) == 0 or len(errors_b) == 0:
                continue
            
            # Perform t-test on absolute errors
            abs_errors_a = np.abs(errors_a)
            abs_errors_b = np.abs(errors_b)
            
            try:
                t_stat, p_value = stats.ttest_ind(abs_errors_a, abs_errors_b)
                
                test_results[f"{regime_a}_vs_{regime_b}"] = {
                    "t_statistic": float(t_stat),
                    "p_value": float(p_value),
                    "significant": p_value < 0.05,
                    "mean_abs_error_a": float(np.mean(abs_errors_a)),
                    "mean_abs_error_b": float(np.mean(abs_errors_b))
                }
            except Exception as e:
                logger.warning(f"Failed to perform t-test for {regime_a} vs {regime_b}: {e}")
    
    return test_results


def load_evaluation_data(
    data_path: Path,
    days: int = 30
) -> pd.DataFrame:
    """Load evaluation data.
    
    Args:
        data_path: Path to data CSV
        days: Number of days to load
        
    Returns:
        DataFrame with evaluation data
    """
    logger.info(f"Loading evaluation data from {data_path}")
    
    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")
    
    df = pd.read_csv(data_path)
    logger.info(f"Loaded {len(df)} samples")
    
    # Filter to last N days if timestamp available
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        cutoff_date = datetime.now() - timedelta(days=days)
        df = df[df["timestamp"] >= cutoff_date]
        logger.info(f"Filtered to {len(df)} samples in last {days} days")
    
    return df


def generate_report(
    metrics_by_regime: Dict[str, Dict[str, float]],
    test_results: Dict[str, Any],
    config: Dict[str, Any],
    output_path: Path
) -> None:
    """Generate regime evaluation report.
    
    Args:
        metrics_by_regime: Metrics for each regime
        test_results: Statistical test results
        config: Evaluation configuration
        output_path: Output path for report
    """
    report = {
        "evaluation_info": {
            "timestamp": datetime.now().isoformat(),
            "index": config.get("index", "NIFTY"),
            "days": config.get("days", 30),
            "regimes_evaluated": list(metrics_by_regime.keys())
        },
        "metrics_by_regime": metrics_by_regime,
        "statistical_tests": test_results,
        "summary": {
            "best_regime": None,
            "worst_regime": None,
            "recommendations": []
        }
    }
    
    # Determine best and worst regimes by MAE
    if metrics_by_regime:
        mae_by_regime = {
            regime: metrics["mae"]
            for regime, metrics in metrics_by_regime.items()
            if not np.isnan(metrics["mae"])
        }
        
        if mae_by_regime:
            best_regime = min(mae_by_regime, key=mae_by_regime.get)
            worst_regime = max(mae_by_regime, key=mae_by_regime.get)
            
            report["summary"]["best_regime"] = best_regime
            report["summary"]["worst_regime"] = worst_regime
            
            # Generate recommendations
            worst_mae = mae_by_regime[worst_regime]
            best_mae = mae_by_regime[best_regime]
            degradation = (worst_mae - best_mae) / best_mae * 100
            
            if degradation > 20:
                report["summary"]["recommendations"].append(
                    f"Performance significantly worse in {worst_regime} regime "
                    f"({degradation:.1f}% degradation). Consider regime-specific models."
                )
            
            # Check coverage
            for regime, metrics in metrics_by_regime.items():
                coverage = metrics.get("coverage", np.nan)
                if not np.isnan(coverage) and coverage < 75:
                    report["summary"]["recommendations"].append(
                        f"Low coverage ({coverage:.1f}%) in {regime} regime. "
                        f"Consider adjusting conformal calibration."
                    )
    
    # Save report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"Report saved to {output_path}")
    
    # Print summary to console
    print("\n" + "="*80)
    print("REGIME-SPECIFIC EVALUATION RESULTS")
    print("="*80)
    
    for regime, metrics in metrics_by_regime.items():
        print(f"\n{regime.upper()}:")
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                print(f"  {key:20s}: {value:.4f}")
    
    if test_results:
        print("\nSTATISTICAL SIGNIFICANCE TESTS:")
        for comparison, result in test_results.items():
            sig_marker = "***" if result["significant"] else ""
            print(f"  {comparison}: p={result['p_value']:.4f} {sig_marker}")
    
    print("\nSUMMARY:")
    print(f"  Best regime: {report['summary']['best_regime']}")
    print(f"  Worst regime: {report['summary']['worst_regime']}")
    if report['summary']['recommendations']:
        print("\n  Recommendations:")
        for rec in report['summary']['recommendations']:
            print(f"    - {rec}")
    
    print("="*80 + "\n")


def main() -> int:
    """Main entry point for regime evaluation."""
    parser = argparse.ArgumentParser(
        description="Evaluate forecaster performance by market regime"
    )
    parser.add_argument(
        "--index",
        type=str,
        default="NIFTY",
        help="Index to evaluate (NIFTY, BANKNIFTY)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to evaluate"
    )
    parser.add_argument(
        "--regimes",
        type=str,
        default="high_vol,low_vol,trending,sideways",
        help="Comma-separated list of regimes to evaluate"
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        help="Path to evaluation data CSV"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/regime_evaluation.json"),
        help="Output path for evaluation report"
    )
    
    args = parser.parse_args()
    
    # Setup configuration
    config = {
        "index": args.index,
        "days": args.days,
        "regimes": args.regimes.split(",")
    }
    
    # Determine data path if not provided
    if args.data_path is None:
        args.data_path = Path(f"data/ml/evaluation/{args.index.lower()}_evaluation_data.csv")
    
    try:
        # Load evaluation data
        df = load_evaluation_data(args.data_path, args.days)
        
        # Compute regime classification thresholds
        iv_high, iv_low = compute_regime_thresholds(df)
        
        # Compute price changes for trend classification
        df["price_change_1h_pct"] = compute_price_change(df)
        
        # Classify each sample
        df["regime"] = df.apply(
            lambda row: classify_regime(row, iv_high, iv_low),
            axis=1
        )
        
        logger.info(f"Regime distribution:\n{df['regime'].value_counts()}")
        
        # Calculate metrics by regime
        metrics_by_regime = calculate_regime_metrics(df)
        
        # Perform statistical tests
        test_results = perform_statistical_tests(df)
        
        # Generate report
        generate_report(metrics_by_regime, test_results, config, args.output)
        
        logger.info("Regime evaluation completed successfully")
        return 0
        
    except Exception as e:
        logger.error(f"Regime evaluation failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
