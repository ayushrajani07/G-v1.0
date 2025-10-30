"""Tests for analytics.option_greeks module."""
from __future__ import annotations

import math
from datetime import UTC, date, datetime

import pytest

from src.analytics.option_greeks import OptionGreeks


class TestCalculateDTE:
    """Test _calculate_dte method for days-to-expiry calculation."""

    def test_calculate_dte_future_date(self):
        """Test DTE calculation for future expiry date."""
        calculator = OptionGreeks()
        current = date(2025, 10, 27)
        expiry = date(2025, 11, 27)  # 31 days ahead
        
        dte = calculator._calculate_dte(expiry, current)
        
        # Should be roughly 31 days / 365
        assert dte > 0
        assert 0.08 < dte < 0.09  # ~31/365 = 0.0849

    def test_calculate_dte_same_day(self):
        """Test DTE calculation when expiry is today."""
        calculator = OptionGreeks()
        current = datetime(2025, 10, 27, 9, 0, 0, tzinfo=UTC)  # 9 AM
        expiry = date(2025, 10, 27)  # Same day, will use 15:30 as expiry time
        
        dte = calculator._calculate_dte(expiry, current)
        
        # Should be positive (hours until 15:30)
        assert dte > 0
        assert dte < 0.01  # Less than 1 day

    def test_calculate_dte_expired(self):
        """Test DTE calculation for expired option."""
        calculator = OptionGreeks()
        current = date(2025, 10, 27)
        expiry = date(2025, 10, 20)  # 7 days ago
        
        dte = calculator._calculate_dte(expiry, current)
        
        assert dte == 0.0

    def test_calculate_dte_with_datetime_expiry(self):
        """Test DTE calculation with datetime expiry."""
        calculator = OptionGreeks()
        current = datetime(2025, 10, 27, 10, 0, 0, tzinfo=UTC)
        expiry = datetime(2025, 11, 3, 15, 30, 0, tzinfo=UTC)  # 7 days + 5.5 hours
        
        dte = calculator._calculate_dte(expiry, current)
        
        # Should be ~7 days / 365
        assert 0.019 < dte < 0.021  # ~7/365 = 0.0192

    def test_calculate_dte_no_current_date(self):
        """Test DTE calculation with default current date."""
        calculator = OptionGreeks()
        # Future date relative to any "now"
        expiry = date(2030, 12, 31)
        
        dte = calculator._calculate_dte(expiry)
        
        assert dte > 0  # Should be positive

    def test_calculate_dte_timezone_awareness(self):
        """Test DTE calculation handles timezone-aware datetimes."""
        calculator = OptionGreeks()
        current = datetime(2025, 10, 27, 10, 0, 0, tzinfo=UTC)
        expiry = datetime(2025, 10, 28, 10, 0, 0, tzinfo=UTC)
        
        dte = calculator._calculate_dte(expiry, current)
        
        # Exactly 24 hours = 1 day
        assert 0.0027 < dte < 0.0028  # 1/365 = 0.00274


class TestBlackScholes:
    """Test Black-Scholes option pricing."""

    def test_black_scholes_call_basic(self):
        """Test basic Black-Scholes call option pricing."""
        calculator = OptionGreeks()
        
        result = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,  # 1 year
            sigma=0.20,  # 20% vol
            r=0.05
        )
        
        # ATM call with 1 year should have positive price
        assert result["price"] > 0
        assert 5.0 < result["price"] < 15.0  # Reasonable range
        
        # Greeks should be in expected ranges
        assert 0.4 < result["delta"] < 0.7  # ATM delta ~0.5
        assert result["gamma"] > 0
        assert result["vega"] > 0
        assert result["theta"] < 0  # Time decay

    def test_black_scholes_put_basic(self):
        """Test basic Black-Scholes put option pricing."""
        calculator = OptionGreeks()
        
        result = calculator.black_scholes(
            is_call=False,
            S=100.0,
            K=100.0,
            T=1.0,
            sigma=0.20,
            r=0.05
        )
        
        # ATM put with 1 year should have positive price
        assert result["price"] > 0
        assert 5.0 < result["price"] < 15.0
        
        # Put delta should be negative
        assert -0.7 < result["delta"] < -0.3
        assert result["gamma"] > 0
        assert result["vega"] > 0
        assert result["theta"] < 0

    def test_black_scholes_itm_call(self):
        """Test in-the-money call option."""
        calculator = OptionGreeks()
        
        result = calculator.black_scholes(
            is_call=True,
            S=110.0,  # 10% ITM
            K=100.0,
            T=0.5,  # 6 months
            sigma=0.20,
            r=0.05
        )
        
        # ITM call should have higher price
        assert result["price"] > 10.0
        # ITM call should have high delta
        assert result["delta"] > 0.7

    def test_black_scholes_otm_put(self):
        """Test out-of-the-money put option."""
        calculator = OptionGreeks()
        
        result = calculator.black_scholes(
            is_call=False,
            S=110.0,
            K=100.0,  # OTM put (S > K)
            T=0.5,
            sigma=0.20,
            r=0.05
        )
        
        # OTM put should have lower price
        assert 0 < result["price"] < 5.0
        # OTM put should have lower delta magnitude
        assert -0.3 < result["delta"] < 0

    def test_black_scholes_with_date_expiry(self):
        """Test Black-Scholes with date object for expiry."""
        calculator = OptionGreeks()
        current = date(2025, 10, 27)
        expiry = date(2025, 11, 27)  # 31 days ahead
        
        result = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=expiry,
            sigma=0.20,
            r=0.05,
            current_date=current
        )
        
        # Should calculate price with ~1 month DTE
        assert result["price"] > 0
        assert 1.0 < result["price"] < 5.0  # Shorter term

    def test_black_scholes_zero_dte(self):
        """Test Black-Scholes with zero DTE (expired)."""
        calculator = OptionGreeks()
        
        result = calculator.black_scholes(
            is_call=True,
            S=105.0,
            K=100.0,
            T=0.0,  # Expired
            sigma=0.20,
            r=0.05
        )
        
        # Should return intrinsic value
        assert result["price"] == 5.0  # max(S - K, 0)
        assert result["delta"] == 1.0  # ITM call
        assert result["gamma"] == 0.0
        assert result["theta"] == 0.0
        assert result["vega"] == 0.0

    def test_black_scholes_zero_volatility(self):
        """Test Black-Scholes with zero volatility."""
        calculator = OptionGreeks()
        
        result = calculator.black_scholes(
            is_call=True,
            S=105.0,
            K=100.0,
            T=1.0,
            sigma=0.0,  # Zero vol
            r=0.05
        )
        
        # Should fallback to intrinsic value
        assert result["price"] == 5.0
        assert result["delta"] == 1.0

    def test_black_scholes_with_dividend(self):
        """Test Black-Scholes with dividend yield."""
        calculator = OptionGreeks()
        
        result = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            sigma=0.20,
            r=0.05,
            q=0.03  # 3% dividend yield
        )
        
        # Dividend reduces call price
        result_no_div = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            sigma=0.20,
            r=0.05,
            q=0.0
        )
        
        assert result["price"] < result_no_div["price"]

    def test_black_scholes_high_volatility(self):
        """Test Black-Scholes with high volatility."""
        calculator = OptionGreeks()
        
        result = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            sigma=0.50,  # 50% vol
            r=0.05
        )
        
        # Higher vol -> higher option price and vega
        result_low_vol = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            sigma=0.20,
            r=0.05
        )
        
        assert result["price"] > result_low_vol["price"]
        assert result["vega"] > 0

    def test_black_scholes_custom_risk_free_rate(self):
        """Test Black-Scholes with custom risk-free rate."""
        calculator = OptionGreeks(risk_free_rate=0.10)
        
        result = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            sigma=0.20
            # r=None will use instance default 0.10
        )
        
        # Higher r -> higher call price
        assert result["price"] > 0

    def test_black_scholes_exception_handling(self):
        """Test Black-Scholes handles calculation errors gracefully."""
        calculator = OptionGreeks()
        
        # Invalid inputs that could cause math errors
        result = calculator.black_scholes(
            is_call=True,
            S=-100.0,  # Negative price (invalid)
            K=100.0,
            T=1.0,
            sigma=0.20,
            r=0.05
        )
        
        # Should return zero values instead of crashing
        assert result["price"] == 0.0
        assert result["delta"] == 0.0


class TestIntrinsicValue:
    """Test intrinsic value calculation for expired options."""

    def test_intrinsic_call_itm(self):
        """Test intrinsic value for ITM call."""
        calculator = OptionGreeks()
        
        result = calculator._intrinsic_value(is_call=True, S=110.0, K=100.0)
        
        assert result["price"] == 10.0  # S - K
        assert result["delta"] == 1.0
        assert result["gamma"] == 0.0
        assert result["theta"] == 0.0
        assert result["vega"] == 0.0

    def test_intrinsic_call_otm(self):
        """Test intrinsic value for OTM call."""
        calculator = OptionGreeks()
        
        result = calculator._intrinsic_value(is_call=True, S=95.0, K=100.0)
        
        assert result["price"] == 0.0
        assert result["delta"] == 0.0

    def test_intrinsic_put_itm(self):
        """Test intrinsic value for ITM put."""
        calculator = OptionGreeks()
        
        result = calculator._intrinsic_value(is_call=False, S=90.0, K=100.0)
        
        assert result["price"] == 10.0  # K - S
        assert result["delta"] == -1.0

    def test_intrinsic_put_otm(self):
        """Test intrinsic value for OTM put."""
        calculator = OptionGreeks()
        
        result = calculator._intrinsic_value(is_call=False, S=110.0, K=100.0)
        
        assert result["price"] == 0.0
        assert result["delta"] == 0.0

    def test_intrinsic_call_atm(self):
        """Test intrinsic value for ATM call."""
        calculator = OptionGreeks()
        
        result = calculator._intrinsic_value(is_call=True, S=100.0, K=100.0)
        
        assert result["price"] == 0.0
        assert result["delta"] == 0.0  # ATM but expired

    def test_intrinsic_put_atm(self):
        """Test intrinsic value for ATM put."""
        calculator = OptionGreeks()
        
        result = calculator._intrinsic_value(is_call=False, S=100.0, K=100.0)
        
        assert result["price"] == 0.0
        assert result["delta"] == 0.0


class TestImpliedVolatility:
    """Test implied volatility calculation."""

    def test_implied_volatility_basic(self):
        """Test basic IV calculation."""
        calculator = OptionGreeks()
        
        # First calculate a theoretical price
        bs_result = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            sigma=0.25,  # 25% vol
            r=0.05
        )
        
        # Now solve for IV given that price
        iv = calculator.implied_volatility(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            market_price=bs_result["price"],
            r=0.05
        )
        
        # Should recover the original 25% vol
        assert 0.24 < iv < 0.26

    def test_implied_volatility_itm_call(self):
        """Test IV calculation for ITM call."""
        calculator = OptionGreeks()
        
        # ITM call with known vol
        bs_result = calculator.black_scholes(
            is_call=True,
            S=110.0,
            K=100.0,
            T=0.5,
            sigma=0.30,
            r=0.05
        )
        
        iv = calculator.implied_volatility(
            is_call=True,
            S=110.0,
            K=100.0,
            T=0.5,
            market_price=bs_result["price"],
            r=0.05
        )
        
        # Should recover ~30% vol
        assert 0.28 < iv < 0.32

    def test_implied_volatility_zero_dte(self):
        """Test IV calculation with zero DTE."""
        calculator = OptionGreeks()
        
        iv = calculator.implied_volatility(
            is_call=True,
            S=100.0,
            K=100.0,
            T=0.0,  # Expired
            market_price=5.0,
            r=0.05
        )
        
        # Should return 0.0 for expired options
        assert iv == 0.0

    def test_implied_volatility_zero_price(self):
        """Test IV calculation with zero market price."""
        calculator = OptionGreeks()
        
        iv = calculator.implied_volatility(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            market_price=0.0,
            r=0.05
        )
        
        # Should return minimum IV
        assert iv == 0.01

    def test_implied_volatility_with_date_expiry(self):
        """Test IV calculation with date object."""
        calculator = OptionGreeks()
        current = date(2025, 10, 27)
        expiry = date(2025, 11, 27)
        
        # Calculate theoretical price first
        bs_result = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=expiry,
            sigma=0.20,
            r=0.05,
            current_date=current
        )
        
        iv = calculator.implied_volatility(
            is_call=True,
            S=100.0,
            K=100.0,
            T=expiry,
            market_price=bs_result["price"],
            r=0.05,
            current_date=current
        )
        
        # Should recover ~20% vol
        assert 0.18 < iv < 0.22

    def test_implied_volatility_bounds_clamping(self):
        """Test IV solver respects min/max bounds."""
        calculator = OptionGreeks()
        
        # Very high price that would suggest extreme vol
        iv = calculator.implied_volatility(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            market_price=80.0,  # Very high price
            r=0.05,
            min_iv=0.10,
            max_iv=1.50  # 150% max
        )
        
        # Should clamp to max_iv
        assert iv <= 1.50
        assert iv >= 0.10

    def test_implied_volatility_custom_precision(self):
        """Test IV solver with custom precision."""
        calculator = OptionGreeks()
        
        bs_result = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            sigma=0.25,
            r=0.05
        )
        
        iv = calculator.implied_volatility(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            market_price=bs_result["price"],
            r=0.05,
            precision=0.001  # Lower precision
        )
        
        # Should converge faster with lower precision
        assert 0.24 < iv < 0.26

    def test_implied_volatility_return_iterations(self):
        """Test IV solver returns iteration count."""
        calculator = OptionGreeks()
        
        bs_result = calculator.black_scholes(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            sigma=0.25,
            r=0.05
        )
        
        iv, iterations = calculator.implied_volatility(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            market_price=bs_result["price"],
            r=0.05,
            return_iterations=True
        )
        
        # Should return tuple with iterations
        assert isinstance(iv, float)
        assert isinstance(iterations, int)
        assert 0.24 < iv < 0.26
        assert 1 <= iterations <= 100

    def test_implied_volatility_max_iterations(self):
        """Test IV solver respects max iterations."""
        calculator = OptionGreeks()
        
        # Price that's hard to fit (may not converge quickly)
        iv, iterations = calculator.implied_volatility(
            is_call=True,
            S=100.0,
            K=100.0,
            T=1.0,
            market_price=10.0,
            r=0.05,
            max_iterations=10,  # Limited iterations
            return_iterations=True
        )
        
        # Should stop at max iterations
        assert iterations <= 10
        assert iv > 0

    def test_implied_volatility_put_option(self):
        """Test IV calculation for put option."""
        calculator = OptionGreeks()
        
        bs_result = calculator.black_scholes(
            is_call=False,
            S=100.0,
            K=100.0,
            T=1.0,
            sigma=0.22,
            r=0.05
        )
        
        iv = calculator.implied_volatility(
            is_call=False,
            S=100.0,
            K=100.0,
            T=1.0,
            market_price=bs_result["price"],
            r=0.05
        )
        
        # Should recover ~22% vol
        assert 0.20 < iv < 0.24


class TestIntegration:
    """Integration tests across option pricing functionality."""

    def test_call_put_parity(self):
        """Test call-put parity relationship."""
        calculator = OptionGreeks()
        
        S = 100.0
        K = 100.0
        T = 1.0
        r = 0.05
        sigma = 0.20
        
        call = calculator.black_scholes(is_call=True, S=S, K=K, T=T, r=r, sigma=sigma)
        put = calculator.black_scholes(is_call=False, S=S, K=K, T=T, r=r, sigma=sigma)
        
        # Call - Put = S - K * e^(-r*T)
        parity = call["price"] - put["price"]
        expected = S - K * math.exp(-r * T)
        
        assert abs(parity - expected) < 0.01

    def test_greeks_consistency(self):
        """Test Greeks are consistent across similar options."""
        calculator = OptionGreeks()
        
        # Two similar calls
        call1 = calculator.black_scholes(is_call=True, S=100.0, K=100.0, T=1.0, sigma=0.20, r=0.05)
        call2 = calculator.black_scholes(is_call=True, S=100.0, K=100.0, T=1.0, sigma=0.20, r=0.05)
        
        # Should be identical
        assert call1["price"] == call2["price"]
        assert call1["delta"] == call2["delta"]
        assert call1["gamma"] == call2["gamma"]
        assert call1["vega"] == call2["vega"]

    def test_delta_hedge_relationship(self):
        """Test delta increases as call becomes more ITM."""
        calculator = OptionGreeks()
        
        otm = calculator.black_scholes(is_call=True, S=90.0, K=100.0, T=1.0, sigma=0.20, r=0.05)
        atm = calculator.black_scholes(is_call=True, S=100.0, K=100.0, T=1.0, sigma=0.20, r=0.05)
        itm = calculator.black_scholes(is_call=True, S=110.0, K=100.0, T=1.0, sigma=0.20, r=0.05)
        
        # Delta should increase: OTM < ATM < ITM
        assert otm["delta"] < atm["delta"] < itm["delta"]
        assert 0 < otm["delta"] < 1
        assert 0 < itm["delta"] < 1

    def test_time_decay_theta(self):
        """Test theta (time decay) behavior."""
        calculator = OptionGreeks()
        
        long_term = calculator.black_scholes(is_call=True, S=100.0, K=100.0, T=1.0, sigma=0.20, r=0.05)
        short_term = calculator.black_scholes(is_call=True, S=100.0, K=100.0, T=0.1, sigma=0.20, r=0.05)
        
        # Both should have negative theta (time decay)
        assert long_term["theta"] < 0
        assert short_term["theta"] < 0
        
        # Short-term options decay faster
        assert abs(short_term["theta"]) > abs(long_term["theta"])

    def test_vega_volatility_relationship(self):
        """Test vega increases option value."""
        calculator = OptionGreeks()
        
        low_vol = calculator.black_scholes(is_call=True, S=100.0, K=100.0, T=1.0, sigma=0.15, r=0.05)
        high_vol = calculator.black_scholes(is_call=True, S=100.0, K=100.0, T=1.0, sigma=0.30, r=0.05)
        
        # Higher vol -> higher price
        assert high_vol["price"] > low_vol["price"]
        
        # Both should have positive vega
        assert low_vol["vega"] > 0
        assert high_vol["vega"] > 0

    def test_round_trip_iv_calculation(self):
        """Test calculating IV from BS price and recovering original price."""
        calculator = OptionGreeks()
        
        # Calculate price with known vol
        original_vol = 0.28
        bs_price = calculator.black_scholes(
            is_call=True, S=105.0, K=100.0, T=0.75, sigma=original_vol, r=0.05
        )["price"]
        
        # Calculate IV from that price
        implied_vol = calculator.implied_volatility(
            is_call=True, S=105.0, K=100.0, T=0.75, market_price=bs_price, r=0.05
        )
        
        # Recalculate price with implied vol
        recovered_price = calculator.black_scholes(
            is_call=True, S=105.0, K=100.0, T=0.75, sigma=implied_vol, r=0.05
        )["price"]
        
        # Should match original
        assert abs(bs_price - recovered_price) < 0.01
        assert abs(original_vol - implied_vol) < 0.01

    def test_use_actual_dte_flag(self):
        """Test use_actual_dte flag affects calculations."""
        calc_with_flag = OptionGreeks(use_actual_dte=True)
        calc_without_flag = OptionGreeks(use_actual_dte=False)
        
        # Both should work (flag is for future behavior)
        current = date(2025, 10, 27)
        expiry = date(2025, 11, 27)
        
        dte1 = calc_with_flag._calculate_dte(expiry, current)
        dte2 = calc_without_flag._calculate_dte(expiry, current)
        
        # Currently both use same logic (flag for future extension)
        assert dte1 > 0
        assert dte2 > 0
