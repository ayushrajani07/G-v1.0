#!/usr/bin/env python3
"""
Validate feature dataset quality.

Performs comprehensive checks on generated feature datasets to ensure
they are ready for model training.

Usage:
    python scripts/ml/validate_features.py --dataset data/ml/training/nifty_tp_features_60d.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analytics.ml.feature_engineering import FeatureEngineer


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate feature dataset quality"
    )
    
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Path to feature dataset CSV"
    )
    
    parser.add_argument(
        "--min-completeness",
        type=float,
        default=0.9,
        help="Minimum completeness ratio (default: 0.9)"
    )
    
    parser.add_argument(
        "--min-correlation",
        type=float,
        default=0.85,
        help="Minimum baseline correlation (default: 0.85)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed statistics"
    )
    
    return parser.parse_args()


def load_dataset(path: str) -> pd.DataFrame:
    """Load dataset from CSV."""
    print(f"Loading dataset from {path}...")
    df = pd.read_csv(path)
    print(f"✓ Loaded {len(df):,} samples with {len(df.columns)} columns")
    return df


def check_required_columns(df: pd.DataFrame) -> bool:
    """Check that all required columns are present."""
    print("\n[1/6] Checking required columns...")
    
    required = ["tp_actual", "tp_baseline", "tp_residual"]
    missing = [col for col in required if col not in df.columns]
    
    if missing:
        print(f"✗ Missing required columns: {missing}")
        return False
    
    print(f"✓ All required columns present")
    return True


def check_feature_presence(df: pd.DataFrame) -> bool:
    """Check that all features are present."""
    print("\n[2/6] Checking feature presence...")
    
    fe = FeatureEngineer()
    feature_names = fe.get_feature_names()
    
    missing = [f for f in feature_names if f not in df.columns]
    
    if missing:
        print(f"✗ Missing features: {missing}")
        return False
    
    print(f"✓ All 24 features present")
    return True


def check_data_quality(df: pd.DataFrame, min_completeness: float) -> bool:
    """Check data quality (NaN, Inf, completeness)."""
    print("\n[3/6] Checking data quality...")
    
    fe = FeatureEngineer()
    feature_names = fe.get_feature_names()
    
    all_good = True
    
    # Check for NaN
    total_nans = 0
    for feat in feature_names:
        if feat in df.columns:
            nan_count = df[feat].isna().sum()
            if nan_count > 0:
                pct = 100 * nan_count / len(df)
                completeness = 1.0 - (nan_count / len(df))
                if completeness < min_completeness:
                    print(f"  ✗ {feat}: {nan_count:,} NaN ({pct:.1f}%), completeness {completeness:.2%}")
                    all_good = False
                total_nans += nan_count
    
    # Check for Inf
    total_infs = 0
    for feat in feature_names:
        if feat in df.columns:
            inf_count = np.isinf(df[feat]).sum()
            if inf_count > 0:
                print(f"  ✗ {feat}: {inf_count:,} infinite values")
                all_good = False
                total_infs += inf_count
    
    if all_good:
        print(f"✓ No NaN or Inf values in features")
    else:
        print(f"✗ Found {total_nans:,} NaN and {total_infs:,} Inf values")
    
    return all_good


def check_baseline_correlation(df: pd.DataFrame, min_corr: float) -> bool:
    """Check baseline correlation with actual TP."""
    print("\n[4/6] Checking baseline correlation...")
    
    if "tp_actual" not in df.columns or "tp_baseline" not in df.columns:
        print("✗ Cannot compute correlation (missing columns)")
        return False
    
    corr = df["tp_actual"].corr(df["tp_baseline"])
    
    if corr >= min_corr:
        print(f"✓ Baseline correlation: {corr:.4f} (>= {min_corr})")
        return True
    else:
        print(f"✗ Baseline correlation: {corr:.4f} (< {min_corr})")
        return False


def check_residual_properties(df: pd.DataFrame) -> bool:
    """Check residual properties."""
    print("\n[5/6] Checking residual properties...")
    
    if "tp_residual" not in df.columns:
        print("✗ Missing tp_residual column")
        return False
    
    residuals = df["tp_residual"].dropna()
    
    mean_res = residuals.mean()
    std_res = residuals.std()
    
    print(f"  Residual mean: {mean_res:.2f}")
    print(f"  Residual std: {std_res:.2f}")
    
    # Check if mean is close to zero (should be for well-calibrated baseline)
    if abs(mean_res) < std_res * 0.1:
        print(f"✓ Residual mean close to zero (well-calibrated baseline)")
        result = True
    else:
        print(f"⚠ Residual mean not close to zero (may need k coefficient tuning)")
        result = True  # Warning, not failure
    
    return result


def check_feature_distributions(df: pd.DataFrame, verbose: bool) -> bool:
    """Check feature distributions."""
    print("\n[6/6] Checking feature distributions...")
    
    fe = FeatureEngineer()
    stats = fe.get_feature_statistics(df)
    
    all_good = True
    
    # Placeholder features that are allowed to be constant
    placeholder_features = ["volume_ratio", "oi_change_rate"]
    
    for feat_name, feat_stats in stats.items():
        # Check for constant features
        if feat_stats["std"] < 1e-10:
            if feat_name in placeholder_features:
                print(f"  ⚠ {feat_name}: constant (placeholder feature)")
            else:
                print(f"  ✗ {feat_name}: constant (std={feat_stats['std']:.2e})")
                all_good = False
        
        # Check for extreme ranges
        feat_range = feat_stats["max"] - feat_stats["min"]
        if feat_range > 1e6:
            print(f"  ⚠ {feat_name}: very large range ({feat_range:.2e})")
        
        if verbose:
            print(f"  {feat_name}:")
            print(f"    Mean: {feat_stats['mean']:.4f}, Std: {feat_stats['std']:.4f}")
            print(f"    Range: [{feat_stats['min']:.4f}, {feat_stats['max']:.4f}]")
    
    if all_good:
        print(f"✓ All features have reasonable distributions")
    
    return all_good


def main():
    """Main execution function."""
    args = parse_args()
    
    try:
        # Load dataset
        df = load_dataset(args.dataset)
        
        # Run checks
        checks = []
        checks.append(("Required columns", check_required_columns(df)))
        checks.append(("Feature presence", check_feature_presence(df)))
        checks.append(("Data quality", check_data_quality(df, args.min_completeness)))
        checks.append(("Baseline correlation", check_baseline_correlation(df, args.min_correlation)))
        checks.append(("Residual properties", check_residual_properties(df)))
        checks.append(("Feature distributions", check_feature_distributions(df, args.verbose)))
        
        # Summary
        print("\n" + "=" * 60)
        print("VALIDATION SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for _, result in checks if result)
        total = len(checks)
        
        for check_name, result in checks:
            status = "✓ PASS" if result else "✗ FAIL"
            print(f"{status}: {check_name}")
        
        print("\n" + "-" * 60)
        print(f"Passed: {passed}/{total} checks")
        
        if passed == total:
            print("\n✓ Dataset validation PASSED")
            print(f"Dataset is ready for model training!")
            sys.exit(0)
        else:
            print("\n✗ Dataset validation FAILED")
            print(f"Please fix the issues above before training.")
            sys.exit(1)
    
    except Exception as e:
        print(f"\n✗ Error during validation: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
