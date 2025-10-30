"""Tests for data quality utilities."""
from __future__ import annotations

import pytest

from src.utils.data_quality import DataQualityChecker


class TestDataQualityChecker:
    """Test suite for DataQualityChecker class."""
    
    @pytest.fixture
    def checker(self):
        """Create a DataQualityChecker instance."""
        return DataQualityChecker()
    
    def test_init(self, checker):
        """Test initialization."""
        assert checker is not None
        assert checker.logger is not None
    
    def test_validate_options_data_empty(self, checker):
        """Test validation with empty data."""
        valid_data, issues = checker.validate_options_data({})
        assert valid_data == {}
        assert "Empty options data" in issues
    
    def test_validate_options_data_valid(self, checker):
        """Test validation with valid data."""
        options_data = {
            'NIFTY25OCT18000CE': {
                'strike': 18000.0,
                'instrument_type': 'CE',
                'last_price': 150.5,
                'expiry': '2025-10-31',
                'tradingsymbol': 'NIFTY25OCT18000CE'
            }
        }
        valid_data, issues = checker.validate_options_data(options_data)
        assert 'NIFTY25OCT18000CE' in valid_data
        assert len(issues) == 0
    
    def test_validate_options_data_invalid_format(self, checker):
        """Test validation with invalid data format."""
        options_data = {
            'NIFTY25OCT18000CE': 'invalid_string'
        }
        valid_data, issues = checker.validate_options_data(options_data)
        assert 'NIFTY25OCT18000CE' not in valid_data
        assert any('Invalid data format' in issue for issue in issues)
    
    def test_validate_options_data_missing_fields(self, checker):
        """Test validation with missing required fields."""
        options_data = {
            'NIFTY25OCT18000CE': {
                'strike': 18000.0,
                # Missing: instrument_type, last_price, expiry, tradingsymbol
            }
        }
        valid_data, issues = checker.validate_options_data(options_data)
        assert 'NIFTY25OCT18000CE' not in valid_data
        assert any('Missing fields' in issue for issue in issues)
    
    def test_validate_options_data_invalid_instrument_type(self, checker):
        """Test validation with invalid instrument type."""
        options_data = {
            'NIFTY25OCT18000XX': {
                'strike': 18000.0,
                'instrument_type': 'XX',  # Invalid
                'last_price': 150.5,
                'expiry': '2025-10-31',
                'tradingsymbol': 'NIFTY25OCT18000XX'
            }
        }
        valid_data, issues = checker.validate_options_data(options_data)
        assert 'NIFTY25OCT18000XX' not in valid_data
        assert any('Invalid instrument_type' in issue for issue in issues)
    
    def test_validate_options_data_negative_price(self, checker):
        """Test validation with negative price."""
        options_data = {
            'NIFTY25OCT18000CE': {
                'strike': 18000.0,
                'instrument_type': 'CE',
                'last_price': -50.0,  # Negative
                'expiry': '2025-10-31',
                'tradingsymbol': 'NIFTY25OCT18000CE'
            }
        }
        valid_data, issues = checker.validate_options_data(options_data)
        assert 'NIFTY25OCT18000CE' not in valid_data
        assert any('Negative price' in issue for issue in issues)
    
    def test_validate_options_data_invalid_price_type(self, checker):
        """Test validation with invalid price type."""
        options_data = {
            'NIFTY25OCT18000CE': {
                'strike': 18000.0,
                'instrument_type': 'CE',
                'last_price': 'not_a_number',
                'expiry': '2025-10-31',
                'tradingsymbol': 'NIFTY25OCT18000CE'
            }
        }
        valid_data, issues = checker.validate_options_data(options_data)
        assert 'NIFTY25OCT18000CE' not in valid_data
        assert any('Invalid price' in issue for issue in issues)
    
    def test_validate_options_data_invalid_strike(self, checker):
        """Test validation with invalid strike."""
        options_data = {
            'NIFTY25OCT18000CE': {
                'strike': 0,  # Invalid (<= 0)
                'instrument_type': 'CE',
                'last_price': 150.5,
                'expiry': '2025-10-31',
                'tradingsymbol': 'NIFTY25OCT18000CE'
            }
        }
        valid_data, issues = checker.validate_options_data(options_data)
        assert 'NIFTY25OCT18000CE' not in valid_data
        assert any('Invalid strike' in issue for issue in issues)
    
    def test_validate_options_data_negative_volume(self, checker):
        """Test validation with negative volume."""
        options_data = {
            'NIFTY25OCT18000CE': {
                'strike': 18000.0,
                'instrument_type': 'CE',
                'last_price': 150.5,
                'expiry': '2025-10-31',
                'tradingsymbol': 'NIFTY25OCT18000CE',
                'volume': -100  # Negative
            }
        }
        valid_data, issues = checker.validate_options_data(options_data)
        # Should still be valid but with issue logged
        assert 'NIFTY25OCT18000CE' in valid_data
        assert any('Negative volume' in issue for issue in issues)
    
    def test_validate_options_data_negative_oi(self, checker):
        """Test validation with negative open interest."""
        options_data = {
            'NIFTY25OCT18000CE': {
                'strike': 18000.0,
                'instrument_type': 'CE',
                'last_price': 150.5,
                'expiry': '2025-10-31',
                'tradingsymbol': 'NIFTY25OCT18000CE',
                'oi': -500  # Negative
            }
        }
        valid_data, issues = checker.validate_options_data(options_data)
        # Should still be valid but with issue logged
        assert 'NIFTY25OCT18000CE' in valid_data
        assert any('Negative OI' in issue for issue in issues)
    
    def test_is_price_outlier_normal(self, checker):
        """Test outlier detection with normal price."""
        option_data = {
            'strike': 18000.0,
            'last_price': 150.0  # ~0.8% of strike
        }
        assert not checker.is_price_outlier(option_data)
    
    def test_is_price_outlier_extreme(self, checker):
        """Test outlier detection with extreme price."""
        option_data = {
            'strike': 18000.0,
            'last_price': 5000.0  # >20% of strike
        }
        assert checker.is_price_outlier(option_data)
    
    def test_check_expiry_consistency_empty(self, checker):
        """Test expiry consistency with empty data."""
        issues = checker.check_expiry_consistency({})
        assert issues == []
    
    def test_check_expiry_consistency_next_week_outlier(self, checker):
        """Test expiry consistency detects next week price outliers."""
        options_data = {
            'OPT1': {
                'last_price': 1000.0,  # Very high
                'instrument_type': 'CE'
            },
            'OPT2': {
                'last_price': 1100.0,
                'instrument_type': 'PE'
            },
            'OPT3': {
                'last_price': 1050.0,
                'instrument_type': 'CE'
            }
        }
        issues = checker.check_expiry_consistency(
            options_data,
            index_price=3000.0,  # Median ~1050 is >30% of 3000
            expiry_rule='next_week'
        )
        assert 'next_week_price_outlier' in issues
    
    def test_check_expiry_consistency_iv_out_of_range(self, checker):
        """Test expiry consistency detects IV out of range."""
        options_data = {
            'OPT1': {
                'last_price': 100.0,
                'iv': 6.0,  # >5.0
                'instrument_type': 'CE'
            }
        }
        issues = checker.check_expiry_consistency(options_data)
        assert 'iv_out_of_range' in issues
    
    def test_check_expiry_consistency_monthly_static_prices(self, checker):
        """Test expiry consistency detects static monthly prices."""
        options_data = {
            'CE1': {'last_price': 100.0, 'instrument_type': 'CE'},
            'CE2': {'last_price': 100.0, 'instrument_type': 'CE'},
            'CE3': {'last_price': 100.0, 'instrument_type': 'CE'},
            'PE1': {'last_price': 200.0, 'instrument_type': 'PE'},
            'PE2': {'last_price': 200.0, 'instrument_type': 'PE'},
            'PE3': {'last_price': 200.0, 'instrument_type': 'PE'},
        }
        issues = checker.check_expiry_consistency(
            options_data,
            expiry_rule='monthly'
        )
        assert 'monthly_ce_price_static' in issues
        assert 'monthly_pe_price_static' in issues
    
    def test_validate_index_data_valid(self, checker):
        """Test index data validation with valid data."""
        is_valid, issues = checker.validate_index_data(18000.0)
        assert is_valid
        assert len(issues) == 0
    
    def test_validate_index_data_invalid_price(self, checker):
        """Test index data validation with invalid price."""
        is_valid, issues = checker.validate_index_data(-100.0)
        assert not is_valid
        assert any('Invalid index price' in issue for issue in issues)
    
    def test_validate_index_data_invalid_format(self, checker):
        """Test index data validation with invalid format."""
        is_valid, issues = checker.validate_index_data('not_a_number')
        assert not is_valid
        assert any('Invalid index price format' in issue for issue in issues)
    
    def test_validate_index_data_with_ohlc_valid(self, checker):
        """Test index data validation with valid OHLC."""
        ohlc = {
            'open': 18000.0,
            'high': 18100.0,
            'low': 17900.0,
            'close': 18050.0
        }
        is_valid, issues = checker.validate_index_data(18050.0, ohlc)
        assert is_valid
        assert len(issues) == 0
    
    def test_validate_index_data_ohlc_missing_field(self, checker):
        """Test index data validation with missing OHLC field."""
        ohlc = {
            'open': 18000.0,
            'high': 18100.0,
            # Missing 'low' and 'close'
        }
        is_valid, issues = checker.validate_index_data(18050.0, ohlc)
        assert not is_valid
        assert any('Missing' in issue for issue in issues)
    
    def test_validate_index_data_ohlc_invalid_value(self, checker):
        """Test index data validation with invalid OHLC value."""
        ohlc = {
            'open': 18000.0,
            'high': -18100.0,  # Negative
            'low': 17900.0,
            'close': 18050.0
        }
        is_valid, issues = checker.validate_index_data(18050.0, ohlc)
        assert not is_valid
        assert any('Invalid high' in issue for issue in issues)
    
    def test_validate_index_data_ohlc_inconsistent(self, checker):
        """Test index data validation with inconsistent OHLC."""
        ohlc = {
            'open': 18000.0,
            'high': 17900.0,  # High < Low
            'low': 18100.0,
            'close': 18050.0
        }
        is_valid, issues = checker.validate_index_data(18050.0, ohlc)
        assert not is_valid
        assert any('High' in issue and 'less than Low' in issue for issue in issues)
    
    def test_get_statistics_empty(self, checker):
        """Test statistics calculation with empty data."""
        stats = checker.get_statistics({})
        assert stats == {}
    
    def test_get_statistics_basic(self, checker):
        """Test statistics calculation with basic data."""
        options_data = {
            'CE1': {
                'instrument_type': 'CE',
                'last_price': 100.0,
                'oi': 1000.0,
                'volume': 500.0
            },
            'CE2': {
                'instrument_type': 'CE',
                'last_price': 150.0,
                'oi': 1500.0,
                'volume': 750.0
            },
            'PE1': {
                'instrument_type': 'PE',
                'last_price': 120.0,
                'oi': 2000.0,
                'volume': 600.0
            },
            'PE2': {
                'instrument_type': 'PE',
                'last_price': 180.0,
                'oi': 2500.0,
                'volume': 900.0
            }
        }
        stats = checker.get_statistics(options_data)
        
        assert stats['call_count'] == 2
        assert stats['put_count'] == 2
        assert stats['total_count'] == 4
        
        # Call statistics
        assert stats['call_price_min'] == 100.0
        assert stats['call_price_max'] == 150.0
        assert stats['call_price_avg'] == 125.0
        assert stats['call_oi_total'] == 2500.0
        assert stats['call_volume_total'] == 1250.0
        
        # Put statistics
        assert stats['put_price_min'] == 120.0
        assert stats['put_price_max'] == 180.0
        assert stats['put_price_avg'] == 150.0
        assert stats['put_oi_total'] == 4500.0
        assert stats['put_volume_total'] == 1500.0
        
        # PCR
        assert 'pcr' in stats
        assert stats['pcr'] == 4500.0 / 2500.0  # put_oi / call_oi
    
    def test_get_statistics_calls_only(self, checker):
        """Test statistics with calls only."""
        options_data = {
            'CE1': {
                'instrument_type': 'CE',
                'last_price': 100.0,
                'oi': 1000.0,
                'volume': 500.0
            }
        }
        stats = checker.get_statistics(options_data)
        
        assert stats['call_count'] == 1
        assert stats['put_count'] == 0
        assert 'call_price_avg' in stats
        assert 'put_price_avg' not in stats
    
    def test_get_statistics_puts_only(self, checker):
        """Test statistics with puts only."""
        options_data = {
            'PE1': {
                'instrument_type': 'PE',
                'last_price': 120.0,
                'oi': 2000.0,
                'volume': 600.0
            }
        }
        stats = checker.get_statistics(options_data)
        
        assert stats['call_count'] == 0
        assert stats['put_count'] == 1
        assert 'put_price_avg' in stats
        assert 'call_price_avg' not in stats


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
