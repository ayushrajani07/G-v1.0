from __future__ import annotations

"""
Feature Engineering Pipeline for TP Forecasting.

Extracts features from historical TP data for ML model training.
Includes lag features, market features, and regime indicators.

Based on ML_ARM_IMPLEMENTATION_ROADMAP.md Phase 1 specifications:
- 24 total features (12 lag, 8 market, 4 regime)
- Designed for GBRT quantile regression
- Compatible with retrieval-based forecasting
"""

import math
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple

import numpy as np
import pandas as pd


@dataclass
class FeatureEngineer:
    """Extract ML features from historical TP data.
    
    Features extracted:
    1. Lag Features (12):
       - TP residual lags: t-1, t-2, t-5, t-10, t-30, t-60
       - Rolling mean residuals: 5min, 15min, 30min
       - Rolling std residuals: 5min, 15min, 30min
    
    2. Market Features (8):
       - Index price return (1min, 5min)
       - Avg IV level and change (1min)
       - Minutes to expiry (normalized)
       - Time-of-day (sin/cos encoding)
       - Weekday (ordinal)
    
    3. Regime Features (4):
       - IV percentile (0-1 scale)
       - Index volatility percentile
       - Volume ratio (current vs. daily avg)
       - OI change rate
    """
    
    # Feature configuration
    lag_periods: List[int] = field(default_factory=lambda: [1, 2, 5, 10, 30, 60])
    rolling_windows: List[int] = field(default_factory=lambda: [5, 15, 30])
    price_return_windows: List[int] = field(default_factory=lambda: [1, 5])
    
    # Normalization bounds
    min_minutes_to_expiry: float = 1.0
    max_minutes_to_expiry: float = 375.0  # Full trading day
    
    def extract_features(
        self,
        df: pd.DataFrame,
        tp_col: str = "tp_actual",
        tp_baseline_col: str = "tp_baseline",
        index_price_col: str = "underlying",
        iv_col: str = "avg_iv",
        minutes_to_expiry_col: str = "minutes_to_expiry",
        timestamp_col: str = "timestamp",
    ) -> pd.DataFrame:
        """Extract all features from a dataframe.
        
        Args:
            df: Input dataframe with historical data
            tp_col: Column name for actual TP values
            tp_baseline_col: Column name for baseline TP values
            index_price_col: Column name for underlying index price
            iv_col: Column name for implied volatility
            minutes_to_expiry_col: Column name for time to expiry
            timestamp_col: Column name for timestamp
            
        Returns:
            DataFrame with all features and target (tp_residual)
        """
        # Make a copy to avoid modifying input
        df = df.copy()
        
        # Ensure timestamp is datetime
        if timestamp_col in df.columns:
            df[timestamp_col] = pd.to_datetime(df[timestamp_col])
        
        # Compute residual (target variable)
        df["tp_residual"] = df[tp_col] - df[tp_baseline_col]
        
        # Extract feature groups
        df = self._extract_lag_features(df)
        df = self._extract_market_features(df, index_price_col, iv_col, 
                                          minutes_to_expiry_col, timestamp_col)
        df = self._extract_regime_features(df, iv_col)
        
        return df
    
    def _extract_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract lag-based features from residuals.
        
        Features:
        - residual_lag_N for N in [1, 2, 5, 10, 30, 60]
        - residual_rolling_mean_N for N in [5, 15, 30]
        - residual_rolling_std_N for N in [5, 15, 30]
        """
        residual = df["tp_residual"]
        
        # Lag features
        for lag in self.lag_periods:
            df[f"residual_lag_{lag}"] = residual.shift(lag)
        
        # Rolling statistics
        for window in self.rolling_windows:
            df[f"residual_rolling_mean_{window}"] = (
                residual.rolling(window=window, min_periods=1).mean()
            )
            df[f"residual_rolling_std_{window}"] = (
                residual.rolling(window=window, min_periods=1).std()
            )
        
        return df
    
    def _extract_market_features(
        self,
        df: pd.DataFrame,
        index_price_col: str,
        iv_col: str,
        minutes_to_expiry_col: str,
        timestamp_col: str,
    ) -> pd.DataFrame:
        """Extract market-related features.
        
        Features:
        - index_return_1m, index_return_5m: Price returns
        - avg_iv: Current IV level
        - iv_change_1m: IV change over 1 minute
        - minutes_to_expiry_norm: Normalized time to expiry
        - time_of_day_sin, time_of_day_cos: Cyclical time encoding
        - weekday: Day of week (0=Monday, 6=Sunday)
        """
        # Price returns
        for window in self.price_return_windows:
            df[f"index_return_{window}m"] = (
                df[index_price_col].pct_change(periods=window)
            )
        
        # IV level (direct copy)
        df["avg_iv"] = df[iv_col]
        
        # IV change
        df["iv_change_1m"] = df[iv_col].diff(periods=1)
        
        # Normalized time to expiry
        df["minutes_to_expiry_norm"] = (
            df[minutes_to_expiry_col].clip(
                lower=self.min_minutes_to_expiry,
                upper=self.max_minutes_to_expiry
            ) / self.max_minutes_to_expiry
        )
        
        # Time of day encoding (assuming timestamp column exists)
        if timestamp_col in df.columns:
            # Extract hour and minute
            hour = df[timestamp_col].dt.hour
            minute = df[timestamp_col].dt.minute
            # Convert to minutes since midnight
            minutes_since_midnight = hour * 60 + minute
            # Normalize to [0, 2π] for cyclical encoding
            angle = 2 * np.pi * minutes_since_midnight / (24 * 60)
            df["time_of_day_sin"] = np.sin(angle)
            df["time_of_day_cos"] = np.cos(angle)
            
            # Weekday (0=Monday, 6=Sunday)
            df["weekday"] = df[timestamp_col].dt.dayofweek
        else:
            # Default values if timestamp not available
            df["time_of_day_sin"] = 0.0
            df["time_of_day_cos"] = 1.0
            df["weekday"] = 0
        
        return df
    
    def _extract_regime_features(
        self,
        df: pd.DataFrame,
        iv_col: str,
    ) -> pd.DataFrame:
        """Extract regime indicators.
        
        Features:
        - iv_percentile: IV percentile over rolling window
        - index_vol_percentile: Index volatility percentile
        - volume_ratio: Current volume vs daily average (placeholder)
        - oi_change_rate: OI change rate (placeholder)
        """
        # IV percentile (rolling 60-period window)
        window = 60
        df["iv_percentile"] = (
            df[iv_col].rolling(window=window, min_periods=1)
            .apply(lambda x: (x.iloc[-1] <= x).mean() if len(x) > 0 else 0.5)
        )
        
        # Index volatility percentile (based on price returns)
        # Use 1-minute returns to compute realized volatility
        if "index_return_1m" in df.columns:
            rolling_vol = df["index_return_1m"].rolling(
                window=window, min_periods=1
            ).std()
            df["index_vol_percentile"] = (
                rolling_vol.rolling(window=window, min_periods=1)
                .apply(lambda x: (x.iloc[-1] <= x).mean() if len(x) > 0 else 0.5)
            )
        else:
            df["index_vol_percentile"] = 0.5
        
        # Volume ratio (placeholder - requires volume data)
        # In production, compute: current_volume / daily_avg_volume
        df["volume_ratio"] = 1.0
        
        # OI change rate (placeholder - requires OI data)
        # In production, compute: (oi_current - oi_prev) / oi_prev
        df["oi_change_rate"] = 0.0
        
        return df
    
    def get_feature_names(self) -> List[str]:
        """Get list of all feature names that will be extracted.
        
        Returns:
            List of feature names (24 total)
        """
        features = []
        
        # Lag features (6)
        for lag in self.lag_periods:
            features.append(f"residual_lag_{lag}")
        
        # Rolling mean features (3)
        for window in self.rolling_windows:
            features.append(f"residual_rolling_mean_{window}")
        
        # Rolling std features (3)
        for window in self.rolling_windows:
            features.append(f"residual_rolling_std_{window}")
        
        # Market features (8)
        for window in self.price_return_windows:
            features.append(f"index_return_{window}m")
        features.extend([
            "avg_iv",
            "iv_change_1m",
            "minutes_to_expiry_norm",
            "time_of_day_sin",
            "time_of_day_cos",
            "weekday",
        ])
        
        # Regime features (4)
        features.extend([
            "iv_percentile",
            "index_vol_percentile",
            "volume_ratio",
            "oi_change_rate",
        ])
        
        return features
    
    def validate_features(
        self,
        df: pd.DataFrame,
        check_nan: bool = True,
        check_inf: bool = True,
    ) -> Tuple[bool, List[str]]:
        """Validate feature quality.
        
        Args:
            df: DataFrame with extracted features
            check_nan: Check for NaN values
            check_inf: Check for infinite values
            
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        feature_names = self.get_feature_names()
        
        # Check if all features exist
        missing_features = set(feature_names) - set(df.columns)
        if missing_features:
            issues.append(f"Missing features: {missing_features}")
        
        # Check for NaN values
        if check_nan:
            for feat in feature_names:
                if feat in df.columns:
                    nan_count = df[feat].isna().sum()
                    if nan_count > 0:
                        nan_pct = 100 * nan_count / len(df)
                        issues.append(
                            f"Feature '{feat}' has {nan_count} NaN values ({nan_pct:.1f}%)"
                        )
        
        # Check for infinite values
        if check_inf:
            for feat in feature_names:
                if feat in df.columns:
                    inf_count = np.isinf(df[feat]).sum()
                    if inf_count > 0:
                        issues.append(
                            f"Feature '{feat}' has {inf_count} infinite values"
                        )
        
        is_valid = len(issues) == 0
        return is_valid, issues
    
    def get_feature_statistics(self, df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
        """Compute basic statistics for all features.
        
        Args:
            df: DataFrame with extracted features
            
        Returns:
            Dictionary mapping feature name to statistics dict
        """
        feature_names = self.get_feature_names()
        stats = {}
        
        for feat in feature_names:
            if feat in df.columns:
                col = df[feat].dropna()
                if len(col) > 0:
                    stats[feat] = {
                        "mean": float(col.mean()),
                        "std": float(col.std()),
                        "min": float(col.min()),
                        "max": float(col.max()),
                        "p25": float(col.quantile(0.25)),
                        "p50": float(col.quantile(0.50)),
                        "p75": float(col.quantile(0.75)),
                        "nan_count": int(df[feat].isna().sum()),
                        "nan_pct": float(100 * df[feat].isna().sum() / len(df)),
                    }
        
        return stats
