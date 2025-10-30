"""Tests for utils.symbol_utils module."""
from __future__ import annotations

import pytest

from src.utils.symbol_utils import (
    normalize_symbol,
    get_segment,
    get_exchange,
    get_strike_step,
    get_display_name,
    INDEX_INFO,
)


class TestIndexInfo:
    """Test INDEX_INFO configuration."""

    def test_index_info_structure(self):
        """Test INDEX_INFO has expected keys and structure."""
        assert "NIFTY" in INDEX_INFO
        assert "BANKNIFTY" in INDEX_INFO
        assert "FINNIFTY" in INDEX_INFO
        assert "MIDCPNIFTY" in INDEX_INFO
        assert "SENSEX" in INDEX_INFO

    def test_index_info_values(self):
        """Test INDEX_INFO values are complete."""
        for symbol, info in INDEX_INFO.items():
            assert "display" in info
            assert "strike_step" in info
            assert "segment" in info
            assert "exchange" in info
            assert isinstance(info["strike_step"], int)
            assert info["strike_step"] > 0

    def test_nifty_info(self):
        """Test NIFTY configuration."""
        info = INDEX_INFO["NIFTY"]
        assert info["display"] == "Nifty 50"
        assert info["strike_step"] == 50
        assert info["segment"] == "NFO-OPT"
        assert info["exchange"] == "NSE"

    def test_banknifty_info(self):
        """Test BANKNIFTY configuration."""
        info = INDEX_INFO["BANKNIFTY"]
        assert info["display"] == "Bank Nifty"
        assert info["strike_step"] == 100
        assert info["segment"] == "NFO-OPT"
        assert info["exchange"] == "NSE"

    def test_sensex_info(self):
        """Test SENSEX configuration (BSE exchange)."""
        info = INDEX_INFO["SENSEX"]
        assert info["display"] == "Sensex"
        assert info["strike_step"] == 100
        assert info["segment"] == "BFO-OPT"
        assert info["exchange"] == "BSE"


class TestNormalizeSymbol:
    """Test normalize_symbol function."""

    def test_normalize_nifty(self):
        """Test normalizing NIFTY symbol."""
        result = normalize_symbol("NIFTY")
        
        assert result["root"] == "NIFTY"
        assert result["display"] == "Nifty 50"
        assert result["strike_step"] == 50
        assert result["segment"] == "NFO-OPT"
        assert result["exchange"] == "NSE"

    def test_normalize_banknifty(self):
        """Test normalizing BANKNIFTY symbol."""
        result = normalize_symbol("BANKNIFTY")
        
        assert result["root"] == "BANKNIFTY"
        assert result["display"] == "Bank Nifty"
        assert result["strike_step"] == 100
        assert result["segment"] == "NFO-OPT"
        assert result["exchange"] == "NSE"

    def test_normalize_sensex(self):
        """Test normalizing SENSEX symbol (BSE)."""
        result = normalize_symbol("SENSEX")
        
        assert result["root"] == "SENSEX"
        assert result["display"] == "Sensex"
        assert result["strike_step"] == 100
        assert result["segment"] == "BFO-OPT"
        assert result["exchange"] == "BSE"

    def test_normalize_lowercase(self):
        """Test normalizing lowercase symbol."""
        result = normalize_symbol("nifty")
        
        assert result["root"] == "NIFTY"
        assert result["display"] == "Nifty 50"

    def test_normalize_mixed_case(self):
        """Test normalizing mixed case symbol."""
        result = normalize_symbol("BaNkNiFtY")
        
        assert result["root"] == "BANKNIFTY"
        assert result["display"] == "Bank Nifty"

    def test_normalize_with_whitespace(self):
        """Test normalizing symbol with leading/trailing whitespace."""
        result = normalize_symbol("  FINNIFTY  ")
        
        assert result["root"] == "FINNIFTY"
        assert result["display"] == "Fin Nifty"
        assert result["strike_step"] == 50

    def test_normalize_empty_string(self):
        """Test normalizing empty string returns UNKNOWN."""
        result = normalize_symbol("")
        
        assert result["root"] == "UNKNOWN"
        assert result["display"] == "Unknown"
        assert result["strike_step"] == 50
        assert result["segment"] == "NFO-OPT"
        assert result["exchange"] == "NSE"

    def test_normalize_unknown_symbol(self):
        """Test normalizing unknown symbol returns defaults."""
        result = normalize_symbol("UNKNOWN_INDEX")
        
        assert result["root"] == "UNKNOWN_INDEX"
        assert result["display"] == "UNKNOWN_INDEX"
        assert result["strike_step"] == 50
        assert result["segment"] == "NFO-OPT"
        assert result["exchange"] == "NSE"

    def test_normalize_partial_match(self):
        """Test normalizing symbol with partial match (prefix)."""
        # Symbol like "NIFTY50" should match "NIFTY"
        result = normalize_symbol("NIFTY50")
        
        assert result["root"] == "NIFTY"
        assert result["display"] == "Nifty 50"
        assert result["strike_step"] == 50

    def test_normalize_midcpnifty(self):
        """Test normalizing MIDCPNIFTY symbol."""
        result = normalize_symbol("MIDCPNIFTY")
        
        assert result["root"] == "MIDCPNIFTY"
        assert result["display"] == "Midcap Nifty"
        assert result["strike_step"] == 25
        assert result["segment"] == "NFO-OPT"
        assert result["exchange"] == "NSE"

    def test_normalize_finnifty(self):
        """Test normalizing FINNIFTY symbol."""
        result = normalize_symbol("FINNIFTY")
        
        assert result["root"] == "FINNIFTY"
        assert result["display"] == "Fin Nifty"
        assert result["strike_step"] == 50


class TestGetSegment:
    """Test get_segment function."""

    def test_get_segment_nifty(self):
        """Test getting segment for NIFTY."""
        segment = get_segment("NIFTY")
        assert segment == "NFO-OPT"

    def test_get_segment_sensex(self):
        """Test getting segment for SENSEX (BFO)."""
        segment = get_segment("SENSEX")
        assert segment == "BFO-OPT"

    def test_get_segment_banknifty(self):
        """Test getting segment for BANKNIFTY."""
        segment = get_segment("BANKNIFTY")
        assert segment == "NFO-OPT"

    def test_get_segment_unknown(self):
        """Test getting segment for unknown symbol (defaults to NFO-OPT)."""
        segment = get_segment("UNKNOWN")
        assert segment == "NFO-OPT"

    def test_get_segment_lowercase(self):
        """Test getting segment with lowercase input."""
        segment = get_segment("nifty")
        assert segment == "NFO-OPT"


class TestGetExchange:
    """Test get_exchange function."""

    def test_get_exchange_nifty(self):
        """Test getting exchange for NIFTY."""
        exchange = get_exchange("NIFTY")
        assert exchange == "NSE"

    def test_get_exchange_sensex(self):
        """Test getting exchange for SENSEX."""
        exchange = get_exchange("SENSEX")
        assert exchange == "BSE"

    def test_get_exchange_banknifty(self):
        """Test getting exchange for BANKNIFTY."""
        exchange = get_exchange("BANKNIFTY")
        assert exchange == "NSE"

    def test_get_exchange_unknown(self):
        """Test getting exchange for unknown symbol (defaults to NSE)."""
        exchange = get_exchange("UNKNOWN")
        assert exchange == "NSE"

    def test_get_exchange_empty(self):
        """Test getting exchange for empty string."""
        exchange = get_exchange("")
        assert exchange == "NSE"

    def test_get_exchange_lowercase(self):
        """Test getting exchange with lowercase input."""
        exchange = get_exchange("sensex")
        assert exchange == "BSE"


class TestGetStrikeStep:
    """Test get_strike_step function."""

    def test_get_strike_step_nifty(self):
        """Test getting strike step for NIFTY."""
        step = get_strike_step("NIFTY")
        assert step == 50

    def test_get_strike_step_banknifty(self):
        """Test getting strike step for BANKNIFTY."""
        step = get_strike_step("BANKNIFTY")
        assert step == 100

    def test_get_strike_step_sensex(self):
        """Test getting strike step for SENSEX."""
        step = get_strike_step("SENSEX")
        assert step == 100

    def test_get_strike_step_midcpnifty(self):
        """Test getting strike step for MIDCPNIFTY."""
        step = get_strike_step("MIDCPNIFTY")
        assert step == 25

    def test_get_strike_step_finnifty(self):
        """Test getting strike step for FINNIFTY."""
        step = get_strike_step("FINNIFTY")
        assert step == 50

    def test_get_strike_step_unknown(self):
        """Test getting strike step for unknown symbol (defaults to 50)."""
        step = get_strike_step("UNKNOWN")
        assert step == 50

    def test_get_strike_step_lowercase(self):
        """Test getting strike step with lowercase input."""
        step = get_strike_step("banknifty")
        assert step == 100


class TestGetDisplayName:
    """Test get_display_name function."""

    def test_get_display_name_nifty(self):
        """Test getting display name for NIFTY."""
        name = get_display_name("NIFTY")
        assert name == "Nifty 50"

    def test_get_display_name_banknifty(self):
        """Test getting display name for BANKNIFTY."""
        name = get_display_name("BANKNIFTY")
        assert name == "Bank Nifty"

    def test_get_display_name_sensex(self):
        """Test getting display name for SENSEX."""
        name = get_display_name("SENSEX")
        assert name == "Sensex"

    def test_get_display_name_finnifty(self):
        """Test getting display name for FINNIFTY."""
        name = get_display_name("FINNIFTY")
        assert name == "Fin Nifty"

    def test_get_display_name_midcpnifty(self):
        """Test getting display name for MIDCPNIFTY."""
        name = get_display_name("MIDCPNIFTY")
        assert name == "Midcap Nifty"

    def test_get_display_name_unknown(self):
        """Test getting display name for unknown symbol (returns symbol itself)."""
        name = get_display_name("UNKNOWN")
        assert name == "UNKNOWN"

    def test_get_display_name_lowercase(self):
        """Test getting display name with lowercase input."""
        name = get_display_name("nifty")
        assert name == "Nifty 50"

    def test_get_display_name_empty(self):
        """Test getting display name for empty string."""
        name = get_display_name("")
        assert name == "Unknown"


class TestIntegration:
    """Integration tests for symbol utilities."""

    def test_all_configured_symbols(self):
        """Test all configured symbols can be normalized and accessed."""
        for symbol in INDEX_INFO.keys():
            # Normalize
            norm = normalize_symbol(symbol)
            assert norm["root"] == symbol
            
            # Get individual fields
            assert get_segment(symbol) == norm["segment"]
            assert get_exchange(symbol) == norm["exchange"]
            assert get_strike_step(symbol) == norm["strike_step"]
            assert get_display_name(symbol) == norm["display"]

    def test_symbol_variations(self):
        """Test various input formats produce consistent results."""
        variations = [
            "NIFTY",
            "nifty",
            "Nifty",
            "NIFTY",
            "  NIFTY  ",
        ]
        
        expected_root = "NIFTY"
        expected_display = "Nifty 50"
        
        for variation in variations:
            norm = normalize_symbol(variation)
            assert norm["root"] == expected_root
            assert norm["display"] == expected_display

    def test_exchange_distinction(self):
        """Test NSE vs BSE distinction."""
        nse_symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
        bse_symbols = ["SENSEX"]
        
        for symbol in nse_symbols:
            assert get_exchange(symbol) == "NSE"
            assert get_segment(symbol) == "NFO-OPT"
        
        for symbol in bse_symbols:
            assert get_exchange(symbol) == "BSE"
            assert get_segment(symbol) == "BFO-OPT"

    def test_strike_step_variation(self):
        """Test strike steps vary by symbol."""
        assert get_strike_step("MIDCPNIFTY") == 25  # Smallest
        assert get_strike_step("NIFTY") == 50
        assert get_strike_step("FINNIFTY") == 50
        assert get_strike_step("BANKNIFTY") == 100  # Largest
        assert get_strike_step("SENSEX") == 100  # Largest

    def test_default_behavior_consistency(self):
        """Test unknown symbols get consistent defaults."""
        unknown_symbols = ["RANDOM", "TEST123", "XYZ"]
        
        for symbol in unknown_symbols:
            norm = normalize_symbol(symbol)
            assert norm["exchange"] == "NSE"
            assert norm["segment"] == "NFO-OPT"
            assert norm["strike_step"] == 50
            # root and display should match the input (uppercase)
            assert norm["root"] == symbol.upper()
            assert norm["display"] == symbol.upper()

    def test_partial_match_behavior(self):
        """Test partial matching for compound symbols."""
        # Symbol like "NIFTY50" should match "NIFTY" prefix
        result = normalize_symbol("NIFTY50")
        assert result["root"] == "NIFTY"
        assert result["display"] == "Nifty 50"
        
        # Symbol like "BANKNIFTY2024" should match "BANKNIFTY" prefix
        result = normalize_symbol("BANKNIFTY2024")
        assert result["root"] == "BANKNIFTY"
        assert result["display"] == "Bank Nifty"

    def test_helper_function_consistency(self):
        """Test helper functions return consistent data with normalize_symbol."""
        symbol = "BANKNIFTY"
        norm = normalize_symbol(symbol)
        
        assert get_segment(symbol) == norm["segment"]
        assert get_exchange(symbol) == norm["exchange"]
        assert get_strike_step(symbol) == norm["strike_step"]
        assert get_display_name(symbol) == norm["display"]
