from src.analytics.ml.baseline import baseline_tp
import math


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
