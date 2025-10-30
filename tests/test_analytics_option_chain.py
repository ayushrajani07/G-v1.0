"""Tests for option chain analytics module."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from src.analytics.option_chain import OptionChainAnalytics


class MockProvider:
    """Mock provider for testing option chain analytics."""
    
    def __init__(self, instruments: list[dict[str, Any]] | None = None, should_fail: bool = False):
        self.instruments = instruments or []
        self.should_fail = should_fail
        self.calls = []
    
    def option_instruments(self, index_symbol: str, expiry_date: date | datetime, strikes: list[float]) -> list[dict[str, Any]]:
        """Mock option instruments method."""
        self.calls.append(('option_instruments', index_symbol, expiry_date, strikes))
        if self.should_fail:
            raise RuntimeError("Provider failure")
        return self.instruments


class TestOptionChainAnalytics:
    """Test suite for OptionChainAnalytics class."""
    
    def test_init(self):
        """Test analytics initialization."""
        provider = MockProvider()
        analytics = OptionChainAnalytics(provider)
        assert analytics.provider is provider
    
    def test_fetch_option_chain_basic(self):
        """Test basic option chain fetch."""
        instruments = [
            {'symbol': 'NIFTY-CE-18000', 'strike': 18000.0, 'type': 'CE'},
            {'symbol': 'NIFTY-PE-18000', 'strike': 18000.0, 'type': 'PE'},
            {'symbol': 'NIFTY-CE-18050', 'strike': 18050.0, 'type': 'CE'},
            {'symbol': 'NIFTY-PE-18050', 'strike': 18050.0, 'type': 'PE'},
        ]
        provider = MockProvider(instruments=instruments)
        analytics = OptionChainAnalytics(provider)
        
        result = analytics.fetch_option_chain(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31),
            strike_range=(18000.0, 18100.0),
            strike_step=50.0
        )
        
        assert isinstance(result, pd.DataFrame)
        assert len(provider.calls) == 1
        assert provider.calls[0][0] == 'option_instruments'
        assert provider.calls[0][1] == 'NIFTY'
    
    def test_fetch_option_chain_auto_strike_step_nifty(self):
        """Test automatic strike step determination for NIFTY."""
        provider = MockProvider(instruments=[])
        analytics = OptionChainAnalytics(provider)
        
        with patch('src.analytics.option_chain.get_index_meta', None):
            result = analytics.fetch_option_chain(
                index_symbol='NIFTY',
                expiry_date=date(2025, 10, 31),
                strike_range=(18000.0, 18100.0),
                strike_step=None
            )
        
        # Should use fallback of 50.0 for NIFTY
        assert isinstance(result, pd.DataFrame)
    
    def test_fetch_option_chain_auto_strike_step_banknifty(self):
        """Test automatic strike step determination for BANKNIFTY."""
        provider = MockProvider(instruments=[])
        analytics = OptionChainAnalytics(provider)
        
        with patch('src.analytics.option_chain.get_index_meta', None):
            result = analytics.fetch_option_chain(
                index_symbol='BANKNIFTY',
                expiry_date=date(2025, 10, 31),
                strike_range=(40000.0, 40200.0),
                strike_step=None
            )
        
        # Should use fallback of 100.0 for BANKNIFTY
        assert isinstance(result, pd.DataFrame)
    
    def test_fetch_option_chain_provider_failure(self):
        """Test handling of provider failures."""
        provider = MockProvider(should_fail=True)
        analytics = OptionChainAnalytics(provider)
        
        result = analytics.fetch_option_chain(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31),
            strike_range=(18000.0, 18100.0),
            strike_step=50.0
        )
        
        # Should return empty DataFrame on error
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
    
    def test_fetch_option_chain_missing_method(self):
        """Test handling when provider lacks option_instruments method."""
        provider = Mock(spec=[])  # Empty spec = no methods
        analytics = OptionChainAnalytics(provider)
        
        result = analytics.fetch_option_chain(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31),
            strike_range=(18000.0, 18100.0),
            strike_step=50.0
        )
        
        # Should return empty DataFrame when method missing
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
    
    def test_fetch_option_chain_alternate_method(self):
        """Test fallback to get_option_instruments method."""
        instruments = [
            {'symbol': 'NIFTY-CE-18000', 'strike': 18000.0, 'type': 'CE'},
        ]
        provider = Mock()
        provider.get_option_instruments = Mock(return_value=instruments)
        # Remove option_instruments to force fallback
        delattr(provider, 'option_instruments')
        
        analytics = OptionChainAnalytics(provider)
        
        result = analytics.fetch_option_chain(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31),
            strike_range=(18000.0, 18050.0),
            strike_step=50.0
        )
        
        assert isinstance(result, pd.DataFrame)
        provider.get_option_instruments.assert_called_once()
    
    def test_fetch_option_chain_datetime_expiry(self):
        """Test with datetime instead of date for expiry."""
        provider = MockProvider(instruments=[])
        analytics = OptionChainAnalytics(provider)
        
        result = analytics.fetch_option_chain(
            index_symbol='NIFTY',
            expiry_date=datetime(2025, 10, 31, 15, 30),
            strike_range=(18000.0, 18100.0),
            strike_step=50.0
        )
        
        assert isinstance(result, pd.DataFrame)
        assert len(provider.calls) == 1
    
    def test_fetch_option_chain_large_strike_range(self):
        """Test with wide strike range."""
        provider = MockProvider(instruments=[])
        analytics = OptionChainAnalytics(provider)
        
        result = analytics.fetch_option_chain(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31),
            strike_range=(15000.0, 21000.0),
            strike_step=100.0
        )
        
        assert isinstance(result, pd.DataFrame)
        # Should generate many strikes
        calls = provider.calls[0]
        strikes_generated = calls[3]
        assert len(strikes_generated) > 50  # (21000-15000)/100 + 1 = 61
    
    def test_fetch_option_chain_single_strike(self):
        """Test with min and max strike equal."""
        provider = MockProvider(instruments=[])
        analytics = OptionChainAnalytics(provider)
        
        result = analytics.fetch_option_chain(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31),
            strike_range=(18000.0, 18000.0),
            strike_step=50.0
        )
        
        assert isinstance(result, pd.DataFrame)
        # Should generate exactly one strike
        calls = provider.calls[0]
        strikes_generated = calls[3]
        assert len(strikes_generated) == 1
        assert strikes_generated[0] == 18000.0


class TestOptionChainIntegration:
    """Integration tests for option chain analytics."""
    
    def test_full_workflow_with_quotes(self):
        """Test complete workflow from fetch to DataFrame with quotes."""
        instruments = [
            {
                'tradingsymbol': 'NIFTY25OCT18000CE',
                'strike': 18000.0,
                'instrument_type': 'CE',
                'expiry': '2025-10-31',
                'exchange': 'NFO'
            },
            {
                'tradingsymbol': 'NIFTY25OCT18000PE',
                'strike': 18000.0,
                'instrument_type': 'PE',
                'expiry': '2025-10-31',
                'exchange': 'NFO'
            },
        ]
        quotes = {
            'NFO:NIFTY25OCT18000CE': {
                'last_price': 150.5,
                'volume': 1000,
                'oi': 5000,
                'buy_quantity': 200,
                'sell_quantity': 180,
                'change': 5.0,
                'depth': {
                    'buy': [{'price': 150.0}],
                    'sell': [{'price': 151.0}]
                }
            },
            'NFO:NIFTY25OCT18000PE': {
                'last_price': 120.0,
                'volume': 800,
                'oi': 4500,
                'buy_quantity': 150,
                'sell_quantity': 170,
                'change': -3.5,
                'depth': {
                    'buy': [{'price': 119.5}],
                    'sell': [{'price': 120.5}]
                }
            }
        }
        
        provider = Mock()
        provider.option_instruments = Mock(return_value=instruments)
        provider.get_quote = Mock(return_value=quotes)
        analytics = OptionChainAnalytics(provider)
        
        df = analytics.fetch_option_chain(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31),
            strike_range=(18000.0, 18000.0),
            strike_step=50.0
        )
        
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        provider.option_instruments.assert_called_once()
        provider.get_quote.assert_called_once()
    
    def test_calculate_pcr_basic(self):
        """Test PCR calculation."""
        instruments = [
            {
                'tradingsymbol': 'NIFTY25OCT18000CE',
                'strike': 18000.0,
                'instrument_type': 'CE',
                'expiry': '2025-10-31',
                'exchange': 'NFO'
            },
            {
                'tradingsymbol': 'NIFTY25OCT18000PE',
                'strike': 18000.0,
                'instrument_type': 'PE',
                'expiry': '2025-10-31',
                'exchange': 'NFO'
            },
        ]
        quotes = {
            'NFO:NIFTY25OCT18000CE': {
                'last_price': 150.5,
                'volume': 1000,
                'oi': 5000,
                'buy_quantity': 0,
                'sell_quantity': 0,
                'change': 0,
                'depth': {'buy': [{'price': 150.0}], 'sell': [{'price': 151.0}]}
            },
            'NFO:NIFTY25OCT18000PE': {
                'last_price': 120.0,
                'volume': 1500,
                'oi': 7500,
                'buy_quantity': 0,
                'sell_quantity': 0,
                'change': 0,
                'depth': {'buy': [{'price': 119.5}], 'sell': [{'price': 120.5}]}
            }
        }
        
        provider = Mock()
        provider.get_atm_strike = Mock(return_value=18000.0)
        provider.option_instruments = Mock(return_value=instruments)
        provider.get_quote = Mock(return_value=quotes)
        analytics = OptionChainAnalytics(provider)
        
        pcr = analytics.calculate_pcr(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31)
        )
        
        assert 'oi_pcr' in pcr
        assert 'volume_pcr' in pcr
        assert isinstance(pcr['oi_pcr'], (int, float))
        assert isinstance(pcr['volume_pcr'], (int, float))
    
    def test_calculate_pcr_empty_chain(self):
        """Test PCR calculation with empty option chain."""
        provider = Mock()
        provider.get_atm_strike = Mock(return_value=18000.0)
        provider.option_instruments = Mock(return_value=[])
        analytics = OptionChainAnalytics(provider)
        
        pcr = analytics.calculate_pcr(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31)
        )
        
        assert pcr['oi_pcr'] == 0.0
        assert pcr['volume_pcr'] == 0.0
    
    def test_calculate_pcr_no_atm_strike_method(self):
        """Test PCR calculation when provider lacks get_atm_strike."""
        provider = Mock(spec=[])  # No methods
        provider.option_instruments = Mock(return_value=[])
        analytics = OptionChainAnalytics(provider)
        
        pcr = analytics.calculate_pcr(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31)
        )
        
        # Should handle gracefully with defaults
        assert pcr['oi_pcr'] == 0.0
        assert pcr['volume_pcr'] == 0.0
    
    def test_calculate_max_pain_basic(self):
        """Test max pain calculation."""
        instruments = [
            {
                'tradingsymbol': 'NIFTY25OCT18000CE',
                'strike': 18000.0,
                'instrument_type': 'CE',
                'expiry': '2025-10-31',
                'exchange': 'NFO'
            },
            {
                'tradingsymbol': 'NIFTY25OCT18000PE',
                'strike': 18000.0,
                'instrument_type': 'PE',
                'expiry': '2025-10-31',
                'exchange': 'NFO'
            },
            {
                'tradingsymbol': 'NIFTY25OCT18100CE',
                'strike': 18100.0,
                'instrument_type': 'CE',
                'expiry': '2025-10-31',
                'exchange': 'NFO'
            },
            {
                'tradingsymbol': 'NIFTY25OCT18100PE',
                'strike': 18100.0,
                'instrument_type': 'PE',
                'expiry': '2025-10-31',
                'exchange': 'NFO'
            },
        ]
        quotes = {
            f'NFO:{inst["tradingsymbol"]}': {
                'last_price': 100.0,
                'volume': 1000,
                'oi': 5000,
                'buy_quantity': 0,
                'sell_quantity': 0,
                'change': 0,
                'depth': {'buy': [{'price': 99.5}], 'sell': [{'price': 100.5}]}
            }
            for inst in instruments
        }
        
        provider = Mock()
        provider.get_atm_strike = Mock(return_value=18050.0)
        provider.option_instruments = Mock(return_value=instruments)
        provider.get_quote = Mock(return_value=quotes)
        analytics = OptionChainAnalytics(provider)
        
        max_pain = analytics.calculate_max_pain(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31)
        )
        
        assert isinstance(max_pain, (int, float))
        assert max_pain > 0
    
    def test_calculate_max_pain_empty_chain(self):
        """Test max pain with empty option chain."""
        provider = Mock()
        provider.get_atm_strike = Mock(return_value=18000.0)
        provider.option_instruments = Mock(return_value=[])
        analytics = OptionChainAnalytics(provider)
        
        max_pain = analytics.calculate_max_pain(
            index_symbol='NIFTY',
            expiry_date=date(2025, 10, 31)
        )
        
        # Should return ATM as fallback
        assert max_pain == 18000.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
