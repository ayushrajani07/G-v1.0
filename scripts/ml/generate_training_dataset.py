#!/usr/bin/env python3
"""
Generate training dataset for ML model training.

Reads historical TP data, computes baseline TP, extracts features,
and generates a training-ready dataset.

Usage:
    python scripts/ml/generate_training_dataset.py \
        --index NIFTY \
        --days 60 \
        --output data/ml/training/nifty_tp_features_60d.csv \
        --compute-baseline \
        --validate

Based on ML_ARM_IMPLEMENTATION_ROADMAP.md Phase 1 specifications.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analytics.ml.baseline import baseline_tp_batch, compute_residuals
from src.analytics.ml.feature_engineering import FeatureEngineer

# Phase 3: Use simplified logging setup
from src.utils.logging_utils import setup_logging
setup_logging(terminal_level='INFO')
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate training dataset for ML models"
    )
    
    parser.add_argument(
        "--input",
        type=str,
        help="Path to input CSV file with historical data"
    )
    
    parser.add_argument(
        "--index",
        type=str,
        default="NIFTY",
        help="Index name (NIFTY, BANKNIFTY, etc.)"
    )
    
    parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="Number of days of historical data to use"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output path for feature matrix CSV"
    )
    
    parser.add_argument(
        "--compute-baseline",
        action="store_true",
        help="Compute baseline TP from structural formula"
    )
    
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Perform data quality validation"
    )
    
    parser.add_argument(
        "--k-coefficient",
        type=float,
        default=1.0,
        help="Baseline scaling coefficient (default: 1.0)"
    )
    
    parser.add_argument(
        "--min-completeness",
        type=float,
        default=0.9,
        help="Minimum data completeness ratio (default: 0.9)"
    )
    
    # Phase 7 arguments
    parser.add_argument(
        "--use-near-strikes",
        action="store_true",
        help="Enable Phase 7 near-strike features (requires ATM±2 strike data)"
    )
    
    parser.add_argument(
        "--use-enhanced-index",
        action="store_true",
        default=True,
        help="Enable Phase 7 enhanced index features (default: True)"
    )
    
    parser.add_argument(
        "--baseline-formula",
        type=str,
        choices=["linear", "sublinear", "log"],
        default="linear",
        help="Baseline formula to use (default: linear)"
    )
    
    return parser.parse_args()


def generate_synthetic_data(
    index: str,
    days: int,
) -> pd.DataFrame:
    """Generate synthetic historical data for testing.
    
    Args:
        index: Index name
        days: Number of days
        
    Returns:
        DataFrame with synthetic data
    """
    logger.info(f"Generating synthetic data for {index} ({days} days)")
    
    # Approximate 375 minutes per trading day
    minutes_per_day = 375
    n_samples = days * minutes_per_day
    
    # Generate timestamps (trading hours: 9:15 AM to 3:30 PM)
    start_date = pd.Timestamp.now() - pd.Timedelta(days=days)
    timestamps = []
    current_ts = start_date
    
    for day in range(days):
        day_start = pd.Timestamp(
            year=current_ts.year,
            month=current_ts.month,
            day=current_ts.day,
            hour=9,
            minute=15
        )
        for minute in range(minutes_per_day):
            timestamps.append(day_start + pd.Timedelta(minutes=minute))
        current_ts = current_ts + pd.Timedelta(days=1)
    
    timestamps = timestamps[:n_samples]  # Trim to exact size
    
    # Generate synthetic market data
    np.random.seed(42)
    
    # Base values depend on index
    if index == "NIFTY":
        base_price = 20000
        base_iv = 0.15
        base_tp = 120
    elif index == "BANKNIFTY":
        base_price = 45000
        base_iv = 0.18
        base_tp = 250
    else:
        base_price = 20000
        base_iv = 0.15
        base_tp = 120
    
    # Generate realistic random walks
    price_returns = np.random.randn(n_samples) * 0.0005  # ~0.05% per minute
    prices = base_price * np.cumprod(1 + price_returns)
    
    iv_changes = np.random.randn(n_samples) * 0.0001
    ivs = np.maximum(base_iv + np.cumsum(iv_changes), 0.05)
    
    # Time to expiry decreases linearly
    minutes_remaining = np.maximum(375 - (np.arange(n_samples) % minutes_per_day), 1)
    T_days = minutes_remaining / (60.0 * 24.0)
    
    # TP follows structural formula with noise
    # baseline_tp = k * underlying * iv * sqrt(T)
    structural_tp = 1.0 * prices * ivs * np.sqrt(T_days)
    # Add noise that's ~5% of structural value
    tp_noise = structural_tp * 0.05 * np.random.randn(n_samples)
    tps = structural_tp + tp_noise
    
    df = pd.DataFrame({
        "timestamp": timestamps,
        "index": index,
        "underlying": prices,
        "ce_iv": ivs * 0.98,  # CE slightly lower
        "pe_iv": ivs * 1.02,  # PE slightly higher
        "avg_iv": ivs,
        "tp_actual": tps,
        "minutes_to_expiry": minutes_remaining,
    })
    
    return df


def load_historical_data(input_path: str) -> pd.DataFrame:
    """Load historical data from CSV or directory of CSVs.
    
    Args:
        input_path: Path to input CSV or directory
        
    Returns:
        DataFrame with historical data
    """
    logger.info(f"Loading historical data from {input_path}")
    path_obj = Path(input_path)
    
    if path_obj.is_dir():
        # Load all CSVs in directory
        csv_files = sorted(list(path_obj.glob("*.csv")))
        if not csv_files:
            raise ValueError(f"No CSV files found in {input_path}")
            
        logger.info(f"Found {len(csv_files)} CSV files")
        dfs = []
        for f in csv_files:
            try:
                # Use on_bad_lines='skip' to handle malformed rows
                df = pd.read_csv(f, on_bad_lines='skip')
                dfs.append(df)
            except Exception as e:
                logger.warning(f"Failed to read {f}: {e}")
        
        if not dfs:
            raise ValueError("Failed to load any data files")
            
        df = pd.concat(dfs, ignore_index=True)
    else:
        # Load single CSV
        df = pd.read_csv(input_path, on_bad_lines='skip')
    
    # Convert timestamp if present
    if "timestamp" in df.columns:
        # Handle mixed formats and coerce errors
        df["timestamp"] = pd.to_datetime(df["timestamp"], dayfirst=True, errors='coerce')
        
        # Drop rows with invalid timestamps
        before_len = len(df)
        df = df.dropna(subset=["timestamp"])
        dropped = before_len - len(df)
        if dropped > 0:
            logger.info(f"Dropped {dropped} rows with invalid timestamps")
            
        # Sort by timestamp
        df = df.sort_values("timestamp")
        
        # Drop duplicates
        before_dedup = len(df)
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        deduped = before_dedup - len(df)
        if deduped > 0:
            logger.info(f"Dropped {deduped} duplicate timestamps")
            
        df = df.reset_index(drop=True)
    
    # Rename columns to match expected schema
    rename_map = {
        "index_price": "underlying",
        "tp": "tp_actual",
        "avg_tp": "tp_baseline" # Some files might have avg_tp which is close to baseline
    }
    df = df.rename(columns=rename_map)
    
    # Calculate avg_iv if missing
    if "avg_iv" not in df.columns:
        if "ce_iv" in df.columns and "pe_iv" in df.columns:
            df["avg_iv"] = (df["ce_iv"] + df["pe_iv"]) / 2.0
            logger.info("Calculated avg_iv from ce_iv and pe_iv")
        elif "iv" in df.columns:
            df["avg_iv"] = df["iv"]
            logger.info("Used iv column as avg_iv")
    
    # Calculate minutes_to_expiry if missing
    if "minutes_to_expiry" not in df.columns and "expiry_date" in df.columns and "timestamp" in df.columns:
        try:
            # Parse expiry date with flexible format
            expiry_dt = pd.to_datetime(df["expiry_date"], dayfirst=True, errors='coerce')
            
            # Drop rows where expiry parsing failed
            if expiry_dt.isna().any():
                logger.warning(f"Dropped {expiry_dt.isna().sum()} rows with invalid expiry dates")
                df = df[expiry_dt.notna()].copy()
                expiry_dt = expiry_dt.dropna()
            
            # Add 15:30 (market close)
            expiry_dt = expiry_dt + pd.Timedelta(hours=15, minutes=30)
            
            # Calculate difference in minutes
            diff = expiry_dt - df["timestamp"]
            df["minutes_to_expiry"] = diff.dt.total_seconds() / 60.0
            
            # Ensure non-negative
            df["minutes_to_expiry"] = df["minutes_to_expiry"].clip(lower=0)
            logger.info("Calculated minutes_to_expiry from expiry_date")
        except Exception as e:
            logger.warning(f"Failed to calculate minutes_to_expiry: {e}")
    
    return df


def compute_baseline(
    df: pd.DataFrame,
    k: float = 1.0,
    formula: str = "linear",
) -> pd.DataFrame:
    """Compute baseline TP and residuals.
    
    Args:
        df: Input dataframe
        k: Baseline scaling coefficient
        formula: Baseline formula to use ("linear", "sublinear", or "log")
        
    Returns:
        DataFrame with baseline and residuals added
    """
    logger.info(f"Computing baseline TP (k={k}, formula={formula})")
    
    # Compute baseline based on formula
    if formula == "linear":
        df = baseline_tp_batch(
            df,
            underlying_col="underlying",
            iv_col="avg_iv",
            minutes_to_expiry_col="minutes_to_expiry",
            output_col="tp_baseline",
            k=k,
        )
    elif formula in ["sublinear", "log"]:
        # Import alternative formulas
        from src.analytics.ml.baseline import baseline_tp_sublinear, baseline_tp_log
        
        # Extract data
        underlying = df["underlying"].values
        iv = df["avg_iv"].values
        minutes_to_expiry = df["minutes_to_expiry"].values
        T = np.maximum(minutes_to_expiry, 1.0) / (60.0 * 24.0)
        
        # Compute baseline
        if formula == "sublinear":
            df["tp_baseline"] = k * np.sqrt(underlying) * iv * np.sqrt(T)
        else:  # log
            df["tp_baseline"] = k * np.log(np.maximum(underlying, 1.0)) * iv * T
    else:
        raise ValueError(f"Unknown baseline formula: {formula}")
    
    # Compute residuals
    df = compute_residuals(
        df,
        tp_actual_col="tp_actual",
        tp_baseline_col="tp_baseline",
        residual_col="tp_residual",
    )
    
    # Log correlation
    corr = df["tp_actual"].corr(df["tp_baseline"])
    logger.info(f"Baseline TP correlation: {corr:.4f}")
    
    return df


def extract_features(
    df: pd.DataFrame,
    use_near_strikes: bool = False,
    use_enhanced_index: bool = True,
) -> pd.DataFrame:
    """Extract ML features.
    
    Args:
        df: Input dataframe with baseline computed
        use_near_strikes: Enable Phase 7 near-strike features
        use_enhanced_index: Enable Phase 7 enhanced index features
        
    Returns:
        DataFrame with features extracted
    """
    logger.info("Extracting features")
    logger.info(f"  Near-strike features: {use_near_strikes}")
    logger.info(f"  Enhanced index features: {use_enhanced_index}")
    
    fe = FeatureEngineer(
        use_near_strikes=use_near_strikes,
        use_enhanced_index=use_enhanced_index,
    )
    
    # Extract features (residual already computed)
    # Need to manually extract lag/market/regime since we have residual
    df_copy = df.copy()
    df_copy = fe._extract_lag_features(df_copy)
    df_copy = fe._extract_market_features(
        df_copy,
        index_price_col="underlying",
        iv_col="avg_iv",
        minutes_to_expiry_col="minutes_to_expiry",
        timestamp_col="timestamp",
    )
    df_copy = fe._extract_regime_features(df_copy, iv_col="avg_iv")
    
    # Phase 7.2: Enhanced index features
    if use_enhanced_index:
        df_copy = fe._extract_enhanced_index_features(
            df_copy,
            index_price_col="underlying",
            iv_col="avg_iv",
            gamma_col=None,  # TODO: Add if available
            vega_col=None,   # TODO: Add if available
        )
    
    # Phase 7.1: Near-strike features
    if use_near_strikes:
        # Check if near-strike columns are available
        near_strike_cols = [
            "ce_atm", "pe_atm", "ce_atm1", "pe_atm1",
            "ce_atm2", "pe_atm2", "volume", "oi"
        ]
        available_cols = [col for col in near_strike_cols if col in df_copy.columns]
        
        if len(available_cols) > 0:
            logger.info(f"  Found {len(available_cols)} near-strike columns")
            df_copy = fe._extract_near_strike_features(
                df_copy,
                ce_atm_col="ce_atm" if "ce_atm" in df_copy.columns else None,
                pe_atm_col="pe_atm" if "pe_atm" in df_copy.columns else None,
                ce_atm1_col="ce_atm1" if "ce_atm1" in df_copy.columns else None,
                pe_atm1_col="pe_atm1" if "pe_atm1" in df_copy.columns else None,
                ce_atm2_col="ce_atm2" if "ce_atm2" in df_copy.columns else None,
                pe_atm2_col="pe_atm2" if "pe_atm2" in df_copy.columns else None,
                ce_atm_minus1_col=None,
                pe_atm_minus1_col=None,
                ce_atm_minus2_col=None,
                pe_atm_minus2_col=None,
                gamma_col=None,
                vega_col=None,
                theta_col=None,
                volume_col="volume" if "volume" in df_copy.columns else None,
                oi_col="oi" if "oi" in df_copy.columns else None,
                iv_col="avg_iv",
            )
        else:
            logger.warning("Near-strike features requested but no strike columns found")
    
    logger.info(f"Extracted {len(fe.get_feature_names())} features")
    
    return df_copy


def validate_dataset(
    df: pd.DataFrame,
    min_completeness: float = 0.9,
) -> Dict[str, Any]:
    """Validate dataset quality.
    
    Args:
        df: Dataset to validate
        min_completeness: Minimum completeness ratio
        
    Returns:
        Dictionary with validation results
    """
    logger.info("Validating dataset")
    
    fe = FeatureEngineer()
    feature_names = fe.get_feature_names()
    
    validation = {
        "total_samples": len(df),
        "features_count": len(feature_names),
        "completeness": {},
        "nan_counts": {},
        "inf_counts": {},
        "passed": True,
        "issues": [],
    }
    
    # Check completeness
    for feat in feature_names:
        if feat in df.columns:
            non_nan = df[feat].notna().sum()
            completeness = non_nan / len(df)
            validation["completeness"][feat] = completeness
            
            if completeness < min_completeness:
                validation["passed"] = False
                validation["issues"].append(
                    f"Feature '{feat}' completeness {completeness:.2%} < {min_completeness:.2%}"
                )
    
    # Check for NaN
    for feat in feature_names:
        if feat in df.columns:
            nan_count = df[feat].isna().sum()
            validation["nan_counts"][feat] = int(nan_count)
    
    # Check for Inf
    for feat in feature_names:
        if feat in df.columns:
            inf_count = np.isinf(df[feat]).sum()
            validation["inf_counts"][feat] = int(inf_count)
            
            if inf_count > 0:
                validation["passed"] = False
                validation["issues"].append(
                    f"Feature '{feat}' has {inf_count} infinite values"
                )
    
    # Check baseline correlation
    if "tp_actual" in df.columns and "tp_baseline" in df.columns:
        corr = df["tp_actual"].corr(df["tp_baseline"])
        validation["baseline_correlation"] = float(corr)
        
        if corr < 0.85:
            validation["passed"] = False
            validation["issues"].append(
                f"Baseline correlation {corr:.4f} < 0.85"
            )
    
    return validation


def save_dataset(
    df: pd.DataFrame,
    output_path: str,
    validation: Optional[Dict[str, Any]] = None,
):
    """Save dataset and metadata.
    
    Args:
        df: Dataset to save
        output_path: Output file path
        validation: Validation results
    """
    logger.info(f"Saving dataset to {output_path}")
    
    # Create output directory
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save dataset
    df.to_csv(output_path, index=False)
    logger.info(f"Saved {len(df)} samples to {output_path}")
    
    # Save statistics
    stats_path = output_path.replace(".csv", "_stats.json")
    fe = FeatureEngineer()
    stats = fe.get_feature_statistics(df)
    
    metadata = {
        "output_file": output_path,
        "total_samples": len(df),
        "features_count": len(fe.get_feature_names()),
        "feature_names": fe.get_feature_names(),
        "feature_statistics": stats,
    }
    
    with open(stats_path, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"Saved statistics to {stats_path}")
    
    # Save validation report
    if validation:
        validation_path = output_path.replace(".csv", "_validation.txt")
        with open(validation_path, "w") as f:
            f.write("Dataset Validation Report\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"Total Samples: {validation['total_samples']}\n")
            f.write(f"Features Count: {validation['features_count']}\n")
            f.write(f"Validation Passed: {validation['passed']}\n\n")
            
            if validation.get("baseline_correlation"):
                f.write(f"Baseline Correlation: {validation['baseline_correlation']:.4f}\n\n")
            
            if validation["issues"]:
                f.write("Issues:\n")
                for issue in validation["issues"]:
                    f.write(f"  - {issue}\n")
            else:
                f.write("No issues found.\n")
        
        logger.info(f"Saved validation report to {validation_path}")


def main():
    """Main execution function."""
    args = parse_args()
    
    try:
        # Load or generate data
        if args.input:
            df = load_historical_data(args.input)
        else:
            logger.warning("No input file specified, generating synthetic data")
            df = generate_synthetic_data(args.index, args.days)
        
        logger.info(f"Loaded {len(df)} samples")
        
        # Compute baseline if requested
        if args.compute_baseline:
            df = compute_baseline(
                df,
                k=args.k_coefficient,
                formula=args.baseline_formula,
            )
        else:
            logger.info("Skipping baseline computation (--compute-baseline not set)")
            # Ensure tp_residual exists
            if "tp_residual" not in df.columns:
                if "tp_actual" in df.columns and "tp_baseline" in df.columns:
                    df["tp_residual"] = df["tp_actual"] - df["tp_baseline"]
        
        # Extract features
        df = extract_features(
            df,
            use_near_strikes=args.use_near_strikes,
            use_enhanced_index=args.use_enhanced_index,
        )
        
        # Validate if requested
        validation = None
        if args.validate:
            validation = validate_dataset(df, min_completeness=args.min_completeness)
            
            if validation["passed"]:
                logger.info("✓ Dataset validation PASSED")
            else:
                logger.warning("✗ Dataset validation FAILED")
                for issue in validation["issues"]:
                    logger.warning(f"  - {issue}")
        
        # Save dataset
        save_dataset(df, args.output, validation)
        
        logger.info("Dataset generation completed successfully")
        
    except Exception as e:
        logger.error(f"Error generating dataset: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
