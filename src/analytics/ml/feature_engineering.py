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
    
    Phase 7 Extensions:
    4. Near-Strike Features (15) - when use_near_strikes=True:
       - Premium ratios (4): CE/PE ratios for ATM±1 and ATM±2
       - Strike skew (4): IV skew and smile curvature (uses real IV data)
       - Greeks gradients (3): Gamma, Vega, Theta gradients (uses real Greeks data)
       - Liquidity indicators (4): Volume/OI concentration, spread, liquidity score (uses real vol/OI)
       
       Note: Uses actual data from collectors which already gather ATM±6 (NIFTY) and ATM±10 (BANKNIFTY) strikes.
    
    5. Enhanced Index Features (8):
       - Signed vs unsigned returns (magnitude and direction)
       - Index-IV correlation (5-min rolling)
       - Realized vs implied vol ratio
       - Index price percentile
       - Interaction features (3): index×IV, index×gamma, index_vol×vega
    """
    
    # Feature configuration
    lag_periods: List[int] = field(default_factory=lambda: [1, 2, 5, 10, 30, 60])
    rolling_windows: List[int] = field(default_factory=lambda: [5, 15, 30])
    price_return_windows: List[int] = field(default_factory=lambda: [1, 5])
    
    # Phase 7 configuration
    use_near_strikes: bool = False  # Enable ATM±2 strike features
    use_enhanced_index: bool = True  # Enable enhanced index features
    
    # Note: Collectors already gather wide strike ranges:
    # - NIFTY: ATM ± 6 strikes (config: strikes_itm=6, strikes_otm=6)
    # - BANKNIFTY: ATM ± 10 strikes (config: strikes_itm=10, strikes_otm=10)
    # Data stored in: data/g6_data/{index}/{expiry}/{offset}/
    # Available fields per offset: ce_iv, pe_iv, ce_gamma, pe_gamma, ce_vega,
    # pe_vega, ce_theta, pe_theta, ce_vol, pe_vol, ce_oi, pe_oi
    
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
        # Phase 7: Near-strike columns (optional)
        ce_atm_col: Optional[str] = None,
        pe_atm_col: Optional[str] = None,
        ce_atm1_col: Optional[str] = None,
        pe_atm1_col: Optional[str] = None,
        ce_atm2_col: Optional[str] = None,
        pe_atm2_col: Optional[str] = None,
        ce_atm_minus1_col: Optional[str] = None,
        pe_atm_minus1_col: Optional[str] = None,
        ce_atm_minus2_col: Optional[str] = None,
        pe_atm_minus2_col: Optional[str] = None,
        # Greeks columns (optional)
        gamma_col: Optional[str] = None,
        vega_col: Optional[str] = None,
        theta_col: Optional[str] = None,
        # Volume/OI columns (optional)
        volume_col: Optional[str] = None,
        oi_col: Optional[str] = None,
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
            ce_atm_col, pe_atm_col: ATM option premiums (for near-strike features)
            ce_atm1_col, pe_atm1_col: ATM+1 strike premiums
            ce_atm2_col, pe_atm2_col: ATM+2 strike premiums
            ce_atm_minus1_col, pe_atm_minus1_col: ATM-1 strike premiums
            ce_atm_minus2_col, pe_atm_minus2_col: ATM-2 strike premiums
            gamma_col, vega_col, theta_col: Greeks columns
            volume_col, oi_col: Volume and open interest columns
            
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
        
        # Phase 7.2: Enhanced index features
        if self.use_enhanced_index:
            df = self._extract_enhanced_index_features(df, index_price_col, iv_col, gamma_col, vega_col)
        
        # Phase 7.1: Near-strike features
        if self.use_near_strikes:
            df = self._extract_near_strike_features(
                df, ce_atm_col, pe_atm_col,
                ce_atm1_col, pe_atm1_col, ce_atm2_col, pe_atm2_col,
                ce_atm_minus1_col, pe_atm_minus1_col, ce_atm_minus2_col, pe_atm_minus2_col,
                gamma_col, vega_col, theta_col,
                volume_col, oi_col, iv_col
            )
        
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
    
    def _extract_enhanced_index_features(
        self,
        df: pd.DataFrame,
        index_price_col: str,
        iv_col: str,
        gamma_col: Optional[str],
        vega_col: Optional[str],
    ) -> pd.DataFrame:
        """Extract enhanced index features (Phase 7.2).
        
        Features:
        - index_return_1m_abs: Absolute value of 1-minute return (magnitude)
        - index_return_1m_sign: Sign of 1-minute return (direction)
        - index_iv_correlation_5m: Rolling correlation between index returns and IV changes
        - rv_iv_ratio: Realized vs implied volatility ratio
        - index_price_percentile: Index price percentile (regime indicator)
        - index_return_x_iv: Interaction feature (index return × IV)
        - index_return_x_gamma: Interaction feature (index return × gamma)
        - index_vol_x_vega: Interaction feature (index volatility × vega)
        """
        # 1. Signed vs Unsigned Returns
        if "index_return_1m" in df.columns:
            df["index_return_1m_abs"] = df["index_return_1m"].abs()
            df["index_return_1m_sign"] = np.sign(df["index_return_1m"])
        else:
            df["index_return_1m_abs"] = 0.0
            df["index_return_1m_sign"] = 0.0
        
        # 2. Index-IV Correlation (5-min rolling window)
        if "index_return_1m" in df.columns and "iv_change_1m" in df.columns:
            window = 5
            df["index_iv_correlation_5m"] = (
                df["index_return_1m"]
                .rolling(window=window, min_periods=2)
                .corr(df["iv_change_1m"])
            )
            # Fill NaN with 0
            df["index_iv_correlation_5m"] = df["index_iv_correlation_5m"].fillna(0.0)
        else:
            df["index_iv_correlation_5m"] = 0.0
        
        # 3. Realized vs Implied Vol Ratio
        if "index_return_1m" in df.columns and iv_col in df.columns:
            # Compute realized volatility (rolling std of returns)
            window = 5
            realized_vol = df["index_return_1m"].rolling(window=window, min_periods=1).std()
            # Avoid division by zero
            implied_vol = df[iv_col].replace(0, np.nan)
            df["rv_iv_ratio"] = (realized_vol / implied_vol).fillna(0.0)
        else:
            df["rv_iv_ratio"] = 0.0
        
        # 4. Index Price Percentile (60-minute lookback)
        if index_price_col in df.columns:
            window = 60
            df["index_price_percentile"] = (
                df[index_price_col].rolling(window=window, min_periods=1)
                .apply(lambda x: (x.iloc[-1] <= x).mean() if len(x) > 0 else 0.5)
            )
        else:
            df["index_price_percentile"] = 0.5
        
        # 5. Interaction Features
        # index_return × IV
        if "index_return_1m" in df.columns and iv_col in df.columns:
            df["index_return_x_iv"] = df["index_return_1m"] * df[iv_col]
        else:
            df["index_return_x_iv"] = 0.0
        
        # index_return × gamma
        if "index_return_1m" in df.columns and gamma_col and gamma_col in df.columns:
            df["index_return_x_gamma"] = df["index_return_1m"] * df[gamma_col]
        else:
            df["index_return_x_gamma"] = 0.0
        
        # index_vol × vega (use 5-min rolling std as index vol)
        if "index_return_1m" in df.columns and vega_col and vega_col in df.columns:
            index_vol = df["index_return_1m"].rolling(window=5, min_periods=1).std()
            df["index_vol_x_vega"] = index_vol * df[vega_col]
        else:
            df["index_vol_x_vega"] = 0.0
        
        return df
    
    def _extract_near_strike_features(
        self,
        df: pd.DataFrame,
        ce_atm_col: Optional[str],
        pe_atm_col: Optional[str],
        ce_atm1_col: Optional[str],
        pe_atm1_col: Optional[str],
        ce_atm2_col: Optional[str],
        pe_atm2_col: Optional[str],
        ce_atm_minus1_col: Optional[str],
        pe_atm_minus1_col: Optional[str],
        ce_atm_minus2_col: Optional[str],
        pe_atm_minus2_col: Optional[str],
        gamma_col: Optional[str],
        vega_col: Optional[str],
        theta_col: Optional[str],
        volume_col: Optional[str],
        oi_col: Optional[str],
        iv_col: str,
    ) -> pd.DataFrame:
        """Extract near-strike features (Phase 7.1).
        
        Features:
        1. Premium Ratios (4):
           - ce_atm1_ratio, pe_atm1_ratio
           - ce_atm2_ratio, pe_atm2_ratio
        2. Strike Skew (4):
           - ce_iv_skew, pe_iv_skew, total_iv_skew, iv_smile_curvature
        3. Greeks Gradients (3):
           - gamma_gradient, vega_gradient, theta_gradient
        4. Liquidity Indicators (4):
           - volume_concentration, oi_concentration, bid_ask_spread_avg, liquidity_score
        """
        # 1. Premium Ratios
        if ce_atm1_col and ce_atm1_col in df.columns and ce_atm_col and ce_atm_col in df.columns:
            ce_atm_safe = df[ce_atm_col].replace(0, np.nan)
            df["ce_atm1_ratio"] = (df[ce_atm1_col] / ce_atm_safe).fillna(1.0)
        else:
            df["ce_atm1_ratio"] = 1.0
        
        if pe_atm1_col and pe_atm1_col in df.columns and pe_atm_col and pe_atm_col in df.columns:
            pe_atm_safe = df[pe_atm_col].replace(0, np.nan)
            df["pe_atm1_ratio"] = (df[pe_atm1_col] / pe_atm_safe).fillna(1.0)
        else:
            df["pe_atm1_ratio"] = 1.0
        
        if ce_atm2_col and ce_atm2_col in df.columns and ce_atm_col and ce_atm_col in df.columns:
            ce_atm_safe = df[ce_atm_col].replace(0, np.nan)
            df["ce_atm2_ratio"] = (df[ce_atm2_col] / ce_atm_safe).fillna(1.0)
        else:
            df["ce_atm2_ratio"] = 1.0
        
        if pe_atm2_col and pe_atm2_col in df.columns and pe_atm_col and pe_atm_col in df.columns:
            pe_atm_safe = df[pe_atm_col].replace(0, np.nan)
            df["pe_atm2_ratio"] = (df[pe_atm2_col] / pe_atm_safe).fillna(1.0)
        else:
            df["pe_atm2_ratio"] = 1.0
        
        # 2. Strike Skew (using IV columns if available)
        # IV skew measures asymmetry in implied volatility across strikes
        # Positive skew: OTM puts > ATM > OTM calls (typical in equity indices)
        
        # CE IV Skew: (IV_ATM - IV_ATM+2) / IV_ATM
        # Measures how CE IV decreases as strike increases
        if ce_atm_col and ce_atm_col in df.columns and ce_atm2_col and ce_atm2_col in df.columns:
            # Assuming IV columns have corresponding naming (e.g., ce_atm -> ce_atm_iv)
            ce_atm_iv_col = f"{ce_atm_col}_iv" if f"{ce_atm_col}_iv" in df.columns else None
            ce_atm2_iv_col = f"{ce_atm2_col}_iv" if f"{ce_atm2_col}_iv" in df.columns else None
            
            if ce_atm_iv_col and ce_atm2_iv_col and ce_atm_iv_col in df.columns and ce_atm2_iv_col in df.columns:
                ce_atm_iv_safe = df[ce_atm_iv_col].replace(0, np.nan)
                df["ce_iv_skew"] = ((df[ce_atm_iv_col] - df[ce_atm2_iv_col]) / ce_atm_iv_safe).fillna(0.0)
            else:
                df["ce_iv_skew"] = 0.0
        else:
            df["ce_iv_skew"] = 0.0
        
        # PE IV Skew: (IV_ATM-2 - IV_ATM) / IV_ATM
        # Measures how PE IV increases as strike decreases (typical put skew)
        if pe_atm_col and pe_atm_col in df.columns and pe_atm_minus2_col and pe_atm_minus2_col in df.columns:
            pe_atm_iv_col = f"{pe_atm_col}_iv" if f"{pe_atm_col}_iv" in df.columns else None
            pe_atm_minus2_iv_col = f"{pe_atm_minus2_col}_iv" if f"{pe_atm_minus2_col}_iv" in df.columns else None
            
            if pe_atm_iv_col and pe_atm_minus2_iv_col and pe_atm_iv_col in df.columns and pe_atm_minus2_iv_col in df.columns:
                pe_atm_iv_safe = df[pe_atm_iv_col].replace(0, np.nan)
                df["pe_iv_skew"] = ((df[pe_atm_minus2_iv_col] - df[pe_atm_iv_col]) / pe_atm_iv_safe).fillna(0.0)
            else:
                df["pe_iv_skew"] = 0.0
        else:
            df["pe_iv_skew"] = 0.0
        
        # Total IV Skew: Combines CE and PE skew
        df["total_iv_skew"] = df["ce_iv_skew"] + df["pe_iv_skew"]
        
        # IV Smile Curvature: Measures convexity of volatility smile
        # Uses ATM-1, ATM, ATM+1 to compute second derivative
        if ce_atm_col and ce_atm1_col and ce_atm_minus1_col:
            ce_atm_iv_col = f"{ce_atm_col}_iv" if f"{ce_atm_col}_iv" in df.columns else None
            ce_atm1_iv_col = f"{ce_atm1_col}_iv" if f"{ce_atm1_col}_iv" in df.columns else None
            ce_atm_minus1_iv_col = f"{ce_atm_minus1_col}_iv" if f"{ce_atm_minus1_col}_iv" in df.columns else None
            
            if (ce_atm_iv_col and ce_atm1_iv_col and ce_atm_minus1_iv_col and
                ce_atm_iv_col in df.columns and ce_atm1_iv_col in df.columns and ce_atm_minus1_iv_col in df.columns):
                # Second derivative approximation: (IV_left + IV_right - 2*IV_center)
                df["iv_smile_curvature"] = (
                    df[ce_atm_minus1_iv_col] + df[ce_atm1_iv_col] - 2 * df[ce_atm_iv_col]
                ).fillna(0.0)
            else:
                df["iv_smile_curvature"] = 0.0
        else:
            df["iv_smile_curvature"] = 0.0
        
        # 3. Greeks Gradients
        # Gradients measure rate of change of Greeks across strikes
        # Helps capture sensitivity changes and convexity effects
        
        # Gamma Gradient: (Gamma_ATM+1 - Gamma_ATM-1) / 2
        # Measures how gamma changes across strikes (gamma is max at ATM)
        if gamma_col and gamma_col in df.columns:
            gamma_atm1_col = f"{gamma_col}_atm1" if f"{gamma_col}_atm1" in df.columns else None
            gamma_atm_minus1_col = f"{gamma_col}_atm_minus1" if f"{gamma_col}_atm_minus1" in df.columns else None
            
            if gamma_atm1_col and gamma_atm_minus1_col:
                df["gamma_gradient"] = (
                    (df[gamma_atm1_col] - df[gamma_atm_minus1_col]) / 2.0
                ).fillna(0.0)
            else:
                # Fallback: use gamma from CE and PE at different strikes if available
                ce_gamma_atm1 = f"{ce_atm1_col}_gamma" if ce_atm1_col and f"{ce_atm1_col}_gamma" in df.columns else None
                ce_gamma_atm_minus1 = f"{ce_atm_minus1_col}_gamma" if ce_atm_minus1_col and f"{ce_atm_minus1_col}_gamma" in df.columns else None
                
                if ce_gamma_atm1 and ce_gamma_atm_minus1:
                    df["gamma_gradient"] = (
                        (df[ce_gamma_atm1] - df[ce_gamma_atm_minus1]) / 2.0
                    ).fillna(0.0)
                else:
                    df["gamma_gradient"] = 0.0
        else:
            df["gamma_gradient"] = 0.0
        
        # Vega Gradient: Similar to gamma gradient
        if vega_col and vega_col in df.columns:
            vega_atm1_col = f"{vega_col}_atm1" if f"{vega_col}_atm1" in df.columns else None
            vega_atm_minus1_col = f"{vega_col}_atm_minus1" if f"{vega_col}_atm_minus1" in df.columns else None
            
            if vega_atm1_col and vega_atm_minus1_col:
                df["vega_gradient"] = (
                    (df[vega_atm1_col] - df[vega_atm_minus1_col]) / 2.0
                ).fillna(0.0)
            else:
                ce_vega_atm1 = f"{ce_atm1_col}_vega" if ce_atm1_col and f"{ce_atm1_col}_vega" in df.columns else None
                ce_vega_atm_minus1 = f"{ce_atm_minus1_col}_vega" if ce_atm_minus1_col and f"{ce_atm_minus1_col}_vega" in df.columns else None
                
                if ce_vega_atm1 and ce_vega_atm_minus1:
                    df["vega_gradient"] = (
                        (df[ce_vega_atm1] - df[ce_vega_atm_minus1]) / 2.0
                    ).fillna(0.0)
                else:
                    df["vega_gradient"] = 0.0
        else:
            df["vega_gradient"] = 0.0
        
        # Theta Gradient: Rate of time decay change across strikes
        if theta_col and theta_col in df.columns:
            theta_atm1_col = f"{theta_col}_atm1" if f"{theta_col}_atm1" in df.columns else None
            theta_atm_minus1_col = f"{theta_col}_atm_minus1" if f"{theta_col}_atm_minus1" in df.columns else None
            
            if theta_atm1_col and theta_atm_minus1_col:
                df["theta_gradient"] = (
                    (df[theta_atm1_col] - df[theta_atm_minus1_col]) / 2.0
                ).fillna(0.0)
            else:
                ce_theta_atm1 = f"{ce_atm1_col}_theta" if ce_atm1_col and f"{ce_atm1_col}_theta" in df.columns else None
                ce_theta_atm_minus1 = f"{ce_atm_minus1_col}_theta" if ce_atm_minus1_col and f"{ce_atm_minus1_col}_theta" in df.columns else None
                
                if ce_theta_atm1 and ce_theta_atm_minus1:
                    df["theta_gradient"] = (
                        (df[ce_theta_atm1] - df[ce_theta_atm_minus1]) / 2.0
                    ).fillna(0.0)
                else:
                    df["theta_gradient"] = 0.0
        else:
            df["theta_gradient"] = 0.0
        
        # 4. Liquidity Indicators
        # These measure how liquidity is distributed across strikes
        
        # Volume Concentration: ATM volume / total volume across ATM±2
        if volume_col and volume_col in df.columns:
            # Calculate total volume across near strikes
            total_vol = df[volume_col]
            
            # Add volumes from other strikes if available
            for strike_col in [ce_atm1_col, ce_atm2_col, ce_atm_minus1_col, ce_atm_minus2_col,
                             pe_atm1_col, pe_atm2_col, pe_atm_minus1_col, pe_atm_minus2_col]:
                if strike_col:
                    vol_col_name = f"{strike_col}_vol" if f"{strike_col}_vol" in df.columns else None
                    if vol_col_name:
                        total_vol = total_vol + df[vol_col_name].fillna(0)
            
            # Compute concentration (avoid division by zero)
            total_vol_safe = total_vol.replace(0, np.nan)
            df["volume_concentration"] = (df[volume_col] / total_vol_safe).fillna(0.5)
            # Clip to reasonable range [0, 1]
            df["volume_concentration"] = df["volume_concentration"].clip(0, 1)
        else:
            df["volume_concentration"] = 0.5
        
        # OI Concentration: ATM OI / total OI across ATM±2
        if oi_col and oi_col in df.columns:
            total_oi = df[oi_col]
            
            # Add OI from other strikes if available
            for strike_col in [ce_atm1_col, ce_atm2_col, ce_atm_minus1_col, ce_atm_minus2_col,
                             pe_atm1_col, pe_atm2_col, pe_atm_minus1_col, pe_atm_minus2_col]:
                if strike_col:
                    oi_col_name = f"{strike_col}_oi" if f"{strike_col}_oi" in df.columns else None
                    if oi_col_name:
                        total_oi = total_oi + df[oi_col_name].fillna(0)
            
            # Compute concentration
            total_oi_safe = total_oi.replace(0, np.nan)
            df["oi_concentration"] = (df[oi_col] / total_oi_safe).fillna(0.5)
            df["oi_concentration"] = df["oi_concentration"].clip(0, 1)
        else:
            df["oi_concentration"] = 0.5
        
        # Bid-ask spread average across strikes
        # If bid/ask columns available, compute spread
        bid_cols = [f"{col}_bid" for col in [ce_atm_col, pe_atm_col, ce_atm1_col, pe_atm1_col] 
                   if col and f"{col}_bid" in df.columns]
        ask_cols = [f"{col}_ask" for col in [ce_atm_col, pe_atm_col, ce_atm1_col, pe_atm1_col]
                   if col and f"{col}_ask" in df.columns]
        
        if bid_cols and ask_cols and len(bid_cols) == len(ask_cols):
            spreads = []
            for bid_col, ask_col in zip(bid_cols, ask_cols):
                mid = (df[bid_col] + df[ask_col]) / 2.0
                mid_safe = mid.replace(0, np.nan)
                spread_pct = ((df[ask_col] - df[bid_col]) / mid_safe).fillna(0)
                spreads.append(spread_pct)
            
            if spreads:
                # Average spread across strikes
                df["bid_ask_spread_avg"] = sum(spreads) / len(spreads)
                df["bid_ask_spread_avg"] = df["bid_ask_spread_avg"].clip(0, 1)
            else:
                df["bid_ask_spread_avg"] = 0.0
        else:
            df["bid_ask_spread_avg"] = 0.0
        
        # Liquidity Score: Composite metric combining volume, OI, and spreads
        # Higher volume/OI concentration and lower spreads indicate better liquidity
        # Formula: 0.4 * vol_conc + 0.4 * oi_conc + 0.2 * (1 - spread)
        df["liquidity_score"] = (
            0.4 * df["volume_concentration"] + 
            0.4 * df["oi_concentration"] +
            0.2 * (1.0 - df["bid_ask_spread_avg"])
        )
        df["liquidity_score"] = df["liquidity_score"].clip(0, 1)
        
        return df
    
    def get_feature_names(self) -> List[str]:
        """Get list of all feature names that will be extracted.
        
        Returns:
            List of feature names (24 base + 8 enhanced index + 15 near-strike = up to 47)
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
        
        # Phase 7.2: Enhanced index features (8)
        if self.use_enhanced_index:
            features.extend([
                "index_return_1m_abs",
                "index_return_1m_sign",
                "index_iv_correlation_5m",
                "rv_iv_ratio",
                "index_price_percentile",
                "index_return_x_iv",
                "index_return_x_gamma",
                "index_vol_x_vega",
            ])
        
        # Phase 7.1: Near-strike features (15)
        if self.use_near_strikes:
            features.extend([
                # Premium ratios (4)
                "ce_atm1_ratio",
                "pe_atm1_ratio",
                "ce_atm2_ratio",
                "pe_atm2_ratio",
                # Strike skew (4)
                "ce_iv_skew",
                "pe_iv_skew",
                "total_iv_skew",
                "iv_smile_curvature",
                # Greeks gradients (3)
                "gamma_gradient",
                "vega_gradient",
                "theta_gradient",
                # Liquidity indicators (4)
                "volume_concentration",
                "oi_concentration",
                "bid_ask_spread_avg",
                "liquidity_score",
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
