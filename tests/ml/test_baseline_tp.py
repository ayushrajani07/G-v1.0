from src.analytics.ml.baseline import baseline_tp, baseline_tp_batch, compute_residuals
import math
import numpy as np
import pandas as pd


def test_baseline_increases_with_underlying_and_iv():
    a = baseline_tp(underlying=100, iv_proxy=0.2, minutes_to_expiry=60)
    b = baseline_tp(underlying=120, iv_proxy=0.2, minutes_to_expiry=60)
    c = baseline_tp(underlying=100, iv_proxy=0.25, minutes_to_expiry=60)
    assert b > a, "Baseline should grow with underlying"
    assert c > a, "Baseline should grow with IV"


def test_baseline_time_sqrt_scaling():
    short = baseline_tp(underlying=100, iv_proxy=0.2, minutes_to_expiry=60)  # 1 hour
    long = baseline_tp(underlying=100, iv_proxy=0.2, minutes_to_expiry=240)  # 4 hours
    # Expect sqrt(4) = 2x ideally (approx)
    ratio = long / short if short > 0 else 0
    assert 1.8 <= ratio <= 2.2, f"Time scaling not ~sqrt, ratio={ratio:.2f}"


def test_baseline_uses_leg_iv_if_proxy_missing():
    # Provide CE/PE IVs
    val = baseline_tp(underlying=100, ce_iv=0.18, pe_iv=0.22, minutes_to_expiry=120)
    # Proxy 0.2 would give similar value; ensure > ce-only baseline
    ce_only = baseline_tp(underlying=100, ce_iv=0.18, minutes_to_expiry=120)
    assert val > ce_only, "Average of CE/PE should exceed CE-only when PE higher"


def test_baseline_minimums():
    # Very small IV, minutes_to_expiry should clamp
    v = baseline_tp(underlying=100, iv_proxy=0.0, minutes_to_expiry=0.0)
    assert v > 0, "Baseline should apply minimum IV and time safeguards"


def test_baseline_zero_underlying():
    v = baseline_tp(underlying=0, iv_proxy=0.2, minutes_to_expiry=60)
    assert v == 0, "Zero underlying should yield zero baseline"


def test_baseline_tp_batch_basic():
    """Test batch baseline computation."""
    df = pd.DataFrame({
        "underlying": [100, 110, 120],
        "avg_iv": [0.2, 0.22, 0.18],
        "minutes_to_expiry": [60, 120, 180],
    })
    
    result = baseline_tp_batch(df, iv_col="avg_iv")
    
    assert "tp_baseline" in result.columns
    assert len(result) == 3
    
    # Check that values are positive
    assert all(result["tp_baseline"] > 0)
    
    # Verify individual calculations
    for i in range(len(df)):
        expected = baseline_tp(
            underlying=df.iloc[i]["underlying"],
            iv_proxy=df.iloc[i]["avg_iv"],
            minutes_to_expiry=df.iloc[i]["minutes_to_expiry"],
        )
        assert np.isclose(result.iloc[i]["tp_baseline"], expected, rtol=1e-5)


def test_baseline_tp_batch_with_ce_pe():
    """Test batch baseline with CE/PE IVs."""
    df = pd.DataFrame({
        "underlying": [100, 110],
        "ce_iv": [0.18, 0.20],
        "pe_iv": [0.22, 0.24],
        "minutes_to_expiry": [60, 120],
    })
    
    result = baseline_tp_batch(df, ce_iv_col="ce_iv", pe_iv_col="pe_iv")
    
    assert "tp_baseline" in result.columns
    assert len(result) == 2
    
    # Verify using averaged IV
    for i in range(len(df)):
        expected = baseline_tp(
            underlying=df.iloc[i]["underlying"],
            iv_proxy=0.5 * (df.iloc[i]["ce_iv"] + df.iloc[i]["pe_iv"]),
            minutes_to_expiry=df.iloc[i]["minutes_to_expiry"],
        )
        assert np.isclose(result.iloc[i]["tp_baseline"], expected, rtol=1e-5)


def test_compute_residuals():
    """Test residual computation."""
    df = pd.DataFrame({
        "tp_actual": [100, 105, 110],
        "tp_baseline": [95, 100, 105],
    })
    
    result = compute_residuals(df)
    
    assert "tp_residual" in result.columns
    assert np.allclose(result["tp_residual"], [5, 5, 5])


def test_baseline_tp_batch_custom_columns():
    """Test batch baseline with custom column names."""
    df = pd.DataFrame({
        "spot": [100, 110],
        "vol": [0.2, 0.22],
        "time": [60, 120],
    })
    
    result = baseline_tp_batch(
        df,
        underlying_col="spot",
        iv_col="vol",
        minutes_to_expiry_col="time",
        output_col="baseline",
    )
    
    assert "baseline" in result.columns
    assert all(result["baseline"] > 0)
