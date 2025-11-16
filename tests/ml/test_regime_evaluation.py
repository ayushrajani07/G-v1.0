"""
Tests for Regime-Specific Evaluation Script (Phase 5)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ml.evaluate_by_regime import (
    MarketRegime,
    classify_regime,
    compute_regime_thresholds,
    compute_price_change
)


def test_classify_high_volatility():
    """Test classification of high volatility regime."""
    row = pd.Series({
        "avg_iv": 0.35,
        "price_change_1h_pct": 0.5
    })
    
    regime = classify_regime(row, iv_high_threshold=0.30, iv_low_threshold=0.15)
    assert regime == MarketRegime.HIGH_VOL


def test_classify_low_volatility():
    """Test classification of low volatility regime."""
    row = pd.Series({
        "avg_iv": 0.12,
        "price_change_1h_pct": 0.5
    })
    
    regime = classify_regime(row, iv_high_threshold=0.30, iv_low_threshold=0.15)
    assert regime == MarketRegime.LOW_VOL


def test_classify_trending():
    """Test classification of trending regime."""
    row = pd.Series({
        "avg_iv": 0.20,  # Between thresholds
        "price_change_1h_pct": 1.5  # Above trend threshold
    })
    
    regime = classify_regime(
        row,
        iv_high_threshold=0.30,
        iv_low_threshold=0.15,
        trend_threshold=1.0
    )
    assert regime == MarketRegime.TRENDING


def test_classify_sideways():
    """Test classification of sideways regime."""
    row = pd.Series({
        "avg_iv": 0.20,  # Between thresholds
        "price_change_1h_pct": 0.2  # Below sideways threshold
    })
    
    regime = classify_regime(
        row,
        iv_high_threshold=0.30,
        iv_low_threshold=0.15,
        sideways_threshold=0.3
    )
    assert regime == MarketRegime.SIDEWAYS


def test_classify_unknown():
    """Test classification with missing data."""
    row = pd.Series({
        "avg_iv": np.nan,
        "price_change_1h_pct": np.nan
    })
    
    regime = classify_regime(row, iv_high_threshold=0.30, iv_low_threshold=0.15)
    assert regime == MarketRegime.UNKNOWN


def test_compute_regime_thresholds():
    """Test computation of IV thresholds."""
    df = pd.DataFrame({
        "avg_iv": [0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.32, 0.35, 0.40]
    })
    
    iv_high, iv_low = compute_regime_thresholds(df)
    
    # 80th percentile should be around 0.34, 20th around 0.17
    assert iv_high > iv_low
    assert 0.30 < iv_high < 0.40
    assert 0.15 < iv_low < 0.20


def test_compute_regime_thresholds_missing_column():
    """Test threshold computation with missing IV column."""
    df = pd.DataFrame({
        "other_col": [1, 2, 3]
    })
    
    iv_high, iv_low = compute_regime_thresholds(df, iv_column="avg_iv")
    
    # Should return defaults
    assert iv_high == 0.3
    assert iv_low == 0.15


def test_compute_price_change():
    """Test price change computation."""
    df = pd.DataFrame({
        "index_price": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    })
    
    price_change = compute_price_change(df, window=3)
    
    # First 3 values should be NaN (window size)
    assert pd.isna(price_change.iloc[0])
    assert pd.isna(price_change.iloc[1])
    assert pd.isna(price_change.iloc[2])
    
    # 4th value should be change from index 0 to 3
    expected_change = ((103.0 - 100.0) / 100.0) * 100
    assert abs(price_change.iloc[3] - expected_change) < 0.01


def test_compute_price_change_missing_column():
    """Test price change with missing column."""
    df = pd.DataFrame({
        "other_col": [1, 2, 3]
    })
    
    price_change = compute_price_change(df, price_column="index_price")
    
    # Should return all NaN
    assert price_change.isna().all()
