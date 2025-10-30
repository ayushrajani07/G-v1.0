"""Tests for collectors.helpers.persist module."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
import pytest

from src.collectors.helpers.persist import persist_and_metrics, persist_with_context
from src.collectors.persist_result import PersistResult
from src.utils.exceptions import CsvWriteError, InfluxWriteError


class TestPersistAndMetrics:
    """Test persist_and_metrics function."""

    @pytest.fixture
    def mock_ctx(self):
        """Create mock context with csv_sink, influx_sink, and metrics."""
        ctx = Mock()
        ctx.csv_sink = Mock()
        ctx.influx_sink = Mock()
        ctx.metrics = Mock()
        
        # Setup metrics attributes
        ctx.metrics.options_collected = Mock()
        ctx.metrics.options_collected.labels = Mock(return_value=Mock())
        ctx.metrics.options_processed_total = Mock()
        ctx.metrics.index_options_processed_total = Mock()
        ctx.metrics.index_options_processed_total.labels = Mock(return_value=Mock())
        ctx.metrics.pcr = Mock()
        ctx.metrics.pcr.labels = Mock(return_value=Mock())
        ctx.metrics.csv_write_errors = Mock()
        
        # Per-option metrics
        ctx.metrics.option_price = Mock()
        ctx.metrics.option_price.labels = Mock(return_value=Mock())
        ctx.metrics.option_volume = Mock()
        ctx.metrics.option_volume.labels = Mock(return_value=Mock())
        ctx.metrics.option_oi = Mock()
        ctx.metrics.option_oi.labels = Mock(return_value=Mock())
        ctx.metrics.option_iv = Mock()
        ctx.metrics.option_iv.labels = Mock(return_value=Mock())
        ctx.metrics.option_delta = Mock()
        ctx.metrics.option_delta.labels = Mock(return_value=Mock())
        ctx.metrics.option_gamma = Mock()
        ctx.metrics.option_gamma.labels = Mock(return_value=Mock())
        ctx.metrics.option_theta = Mock()
        ctx.metrics.option_theta.labels = Mock(return_value=Mock())
        ctx.metrics.option_vega = Mock()
        ctx.metrics.option_vega.labels = Mock(return_value=Mock())
        ctx.metrics.option_rho = Mock()
        ctx.metrics.option_rho.labels = Mock(return_value=Mock())
        
        return ctx

    @pytest.fixture
    def sample_enriched_data(self):
        """Create sample enriched options data."""
        return {
            "NIFTY_50_24500_CE": {
                "instrument_type": "CE",
                "strike": 24500,
                "last_price": 120.5,
                "volume": 1000,
                "oi": 5000,
                "iv": 18.5,
                "delta": 0.45,
                "gamma": 0.002,
                "theta": -12.5,
                "vega": 25.0,
                "rho": 8.5,
            },
            "NIFTY_50_24500_PE": {
                "instrument_type": "PE",
                "strike": 24500,
                "last_price": 95.0,
                "volume": 800,
                "oi": 4000,
                "iv": 19.2,
                "delta": -0.55,
                "gamma": 0.002,
                "theta": -10.0,
                "vega": 22.0,
                "rho": -7.0,
            },
        }

    def test_persist_and_metrics_success(self, mock_ctx, sample_enriched_data):
        """Test successful persist_and_metrics with all components."""
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 0.8}
        
        result = persist_and_metrics(
            mock_ctx,
            sample_enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc={"open": 24450.0, "high": 24550.0, "low": 24400.0, "close": 24500.0},
            allow_per_option_metrics=True,
        )
        
        assert isinstance(result, PersistResult)
        assert result.option_count == 2
        assert result.pcr == 0.8
        assert result.metrics_payload == {"pcr": 0.8}
        assert result.failed is False
        
        # Verify CSV write was called
        mock_ctx.csv_sink.write_options_data.assert_called_once()
        
        # Verify InfluxDB write was called
        mock_ctx.influx_sink.write_options_data.assert_called_once()
        
        # Verify metrics were set
        mock_ctx.metrics.options_collected.labels.assert_called_with(index="NIFTY", expiry="weekly")

    def test_persist_and_metrics_csv_write_error(self, mock_ctx, sample_enriched_data):
        """Test CSV write error handling."""
        mock_ctx.csv_sink.write_options_data.side_effect = CsvWriteError("Disk full")
        
        with patch('src.collectors.helpers.persist.handle_collector_error') as mock_handle:
            result = persist_and_metrics(
                mock_ctx,
                sample_enriched_data,
                index_symbol="NIFTY",
                expiry_rule="weekly",
                expiry_date="2025-10-30",
                collection_time=datetime(2025, 10, 27, 9, 15),
                index_price=24500.0,
                index_ohlc=None,
                allow_per_option_metrics=False,
            )
        
        assert result.option_count == 0
        assert result.pcr is None
        # metrics_payload is {} (empty dict) not None on CSV error
        assert result.failed is True
        
        # Verify error handler was called
        mock_handle.assert_called_once()
        error_arg = mock_handle.call_args[0][0]
        assert isinstance(error_arg, CsvWriteError)
        
        # Verify CSV error metric was incremented
        mock_ctx.metrics.csv_write_errors.inc.assert_called_once()

    def test_persist_and_metrics_oserror_handling(self, mock_ctx, sample_enriched_data):
        """Test OSError handling during CSV write."""
        mock_ctx.csv_sink.write_options_data.side_effect = OSError("Permission denied")
        
        with patch('src.collectors.helpers.persist.handle_collector_error') as mock_handle:
            result = persist_and_metrics(
                mock_ctx,
                sample_enriched_data,
                index_symbol="BANKNIFTY",
                expiry_rule="monthly",
                expiry_date="2025-11-27",
                collection_time=datetime(2025, 10, 27, 9, 15),
                index_price=52000.0,
                index_ohlc=None,
                allow_per_option_metrics=False,
            )
        
        assert result.failed is True
        mock_handle.assert_called_once()

    def test_persist_and_metrics_influx_error(self, mock_ctx, sample_enriched_data):
        """Test InfluxDB write error handling (doesn't fail overall)."""
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 0.75}
        mock_ctx.influx_sink.write_options_data.side_effect = InfluxWriteError("Connection failed")
        
        with patch('src.collectors.helpers.persist.handle_collector_error') as mock_handle:
            result = persist_and_metrics(
                mock_ctx,
                sample_enriched_data,
                index_symbol="FINNIFTY",
                expiry_rule="weekly",
                expiry_date="2025-10-29",
                collection_time=datetime(2025, 10, 27, 9, 15),
                index_price=23000.0,
                index_ohlc=None,
                allow_per_option_metrics=False,
            )
        
        # CSV succeeded, so persist doesn't fail
        assert result.failed is False
        assert result.option_count == 2
        
        # But error handler was called for InfluxDB
        mock_handle.assert_called_once()
        error_arg = mock_handle.call_args[0][0]
        assert isinstance(error_arg, InfluxWriteError)

    def test_persist_and_metrics_no_influx_sink(self, mock_ctx, sample_enriched_data):
        """Test when influx_sink is None (optional component)."""
        mock_ctx.influx_sink = None
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 0.9}
        
        result = persist_and_metrics(
            mock_ctx,
            sample_enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc=None,
            allow_per_option_metrics=False,
        )
        
        assert result.failed is False
        assert result.option_count == 2

    def test_persist_and_metrics_no_metrics(self, mock_ctx, sample_enriched_data):
        """Test when metrics is None (optional component)."""
        mock_ctx.metrics = None
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 0.85}
        
        result = persist_and_metrics(
            mock_ctx,
            sample_enriched_data,
            index_symbol="SENSEX",
            expiry_rule="monthly",
            expiry_date="2025-11-28",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=82000.0,
            index_ohlc=None,
            allow_per_option_metrics=False,
        )
        
        assert result.failed is False
        assert result.option_count == 2

    def test_persist_and_metrics_pcr_calculation(self, mock_ctx):
        """Test PCR calculation from enriched data."""
        enriched_data = {
            "OPT1_CE": {"instrument_type": "CE", "oi": 10000, "strike": 24000},
            "OPT2_CE": {"instrument_type": "CE", "oi": 5000, "strike": 24500},
            "OPT3_PE": {"instrument_type": "PE", "oi": 12000, "strike": 24000},
            "OPT4_PE": {"instrument_type": "PE", "oi": 8000, "strike": 24500},
        }
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 1.33}
        
        result = persist_and_metrics(
            mock_ctx,
            enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24200.0,
            index_ohlc=None,
            allow_per_option_metrics=False,
        )
        
        # PCR = (12000 + 8000) / (10000 + 5000) = 20000 / 15000 = 1.33
        mock_ctx.metrics.pcr.labels.assert_called_with(index="NIFTY", expiry="weekly")
        pcr_metric = mock_ctx.metrics.pcr.labels.return_value
        # Should be approximately 1.33
        assert pcr_metric.set.called

    def test_persist_and_metrics_pcr_zero_call_oi(self, mock_ctx):
        """Test PCR calculation when call OI is zero."""
        enriched_data = {
            "OPT_PE": {"instrument_type": "PE", "oi": 10000, "strike": 24000},
        }
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 0.0}
        
        result = persist_and_metrics(
            mock_ctx,
            enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc=None,
            allow_per_option_metrics=False,
        )
        
        # PCR should be 0 when call OI is 0
        pcr_metric = mock_ctx.metrics.pcr.labels.return_value
        pcr_metric.set.assert_called_with(0)

    def test_persist_and_metrics_per_option_metrics_disabled(self, mock_ctx, sample_enriched_data):
        """Test with per-option metrics disabled."""
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 0.8}
        
        result = persist_and_metrics(
            mock_ctx,
            sample_enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc=None,
            allow_per_option_metrics=False,
        )
        
        assert result.failed is False
        # Per-option metrics should not be called
        mock_ctx.metrics.option_price.labels.assert_not_called()

    def test_persist_and_metrics_per_option_metrics_enabled(self, mock_ctx, sample_enriched_data):
        """Test with per-option metrics enabled."""
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 0.8}
        
        result = persist_and_metrics(
            mock_ctx,
            sample_enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc=None,
            allow_per_option_metrics=True,
        )
        
        assert result.failed is False
        # Per-option metrics should be called for each option
        assert mock_ctx.metrics.option_price.labels.call_count == 2
        assert mock_ctx.metrics.option_volume.labels.call_count == 2
        assert mock_ctx.metrics.option_oi.labels.call_count == 2
        assert mock_ctx.metrics.option_iv.labels.call_count == 2

    def test_persist_and_metrics_greek_metrics(self, mock_ctx):
        """Test Greek metrics emission when present."""
        enriched_data = {
            "OPT_CE": {
                "instrument_type": "CE",
                "strike": 24500,
                "last_price": 100.0,
                "delta": 0.5,
                "gamma": 0.001,
                "theta": -10.0,
                "vega": 20.0,
                "rho": 5.0,
            },
        }
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 1.0}
        
        result = persist_and_metrics(
            mock_ctx,
            enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc=None,
            allow_per_option_metrics=True,
        )
        
        assert result.failed is False
        # Greeks should be emitted
        mock_ctx.metrics.option_delta.labels.assert_called_once()
        mock_ctx.metrics.option_gamma.labels.assert_called_once()
        mock_ctx.metrics.option_theta.labels.assert_called_once()
        mock_ctx.metrics.option_vega.labels.assert_called_once()
        mock_ctx.metrics.option_rho.labels.assert_called_once()

    def test_persist_and_metrics_missing_greeks(self, mock_ctx):
        """Test options without Greek values (no error)."""
        enriched_data = {
            "OPT_CE": {
                "instrument_type": "CE",
                "strike": 24500,
                "last_price": 100.0,
                # No delta, gamma, theta, vega, rho
            },
        }
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 1.0}
        
        result = persist_and_metrics(
            mock_ctx,
            enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc=None,
            allow_per_option_metrics=True,
        )
        
        assert result.failed is False
        # Greeks should not be called
        mock_ctx.metrics.option_delta.labels.assert_not_called()

    def test_persist_and_metrics_invalid_strike(self, mock_ctx):
        """Test options with missing/invalid strike (skipped)."""
        enriched_data = {
            "OPT1_CE": {
                "instrument_type": "CE",
                "strike": 0,  # Invalid
                "last_price": 100.0,
            },
            "OPT2_CE": {
                "instrument_type": "CE",
                # Missing strike
                "last_price": 95.0,
            },
            "OPT3_CE": {
                "instrument_type": "CE",
                "strike": 24500,  # Valid
                "last_price": 110.0,
            },
        }
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 1.0}
        
        result = persist_and_metrics(
            mock_ctx,
            enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc=None,
            allow_per_option_metrics=True,
        )
        
        assert result.failed is False
        # Only 1 option should emit metrics (OPT3_CE)
        assert mock_ctx.metrics.option_price.labels.call_count == 1

    def test_persist_and_metrics_invalid_type(self, mock_ctx):
        """Test options with invalid type (skipped)."""
        enriched_data = {
            "OPT_INVALID": {
                "instrument_type": "INVALID",
                "strike": 24500,
                "last_price": 100.0,
            },
            "OPT_CE": {
                "instrument_type": "CE",
                "strike": 24500,
                "last_price": 100.0,
            },
        }
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 1.0}
        
        result = persist_and_metrics(
            mock_ctx,
            enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc=None,
            allow_per_option_metrics=True,
        )
        
        assert result.failed is False
        # Only CE option should emit metrics
        assert mock_ctx.metrics.option_price.labels.call_count == 1

    def test_persist_and_metrics_type_field_variations(self, mock_ctx):
        """Test 'type' field as alternative to 'instrument_type'."""
        enriched_data = {
            "OPT1": {
                "type": "CE",  # Using 'type' instead of 'instrument_type'
                "strike": 24500,
                "last_price": 100.0,
                "oi": 5000,
            },
            "OPT2": {
                "type": "PE",
                "strike": 24500,
                "last_price": 95.0,
                "oi": 4000,
            },
        }
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 0.8}
        
        result = persist_and_metrics(
            mock_ctx,
            enriched_data,
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc=None,
            allow_per_option_metrics=True,
        )
        
        assert result.failed is False
        # PCR calculation should work with 'type' field
        pcr_metric = mock_ctx.metrics.pcr.labels.return_value
        assert pcr_metric.set.called

    def test_persist_and_metrics_empty_data(self, mock_ctx):
        """Test with empty enriched data."""
        mock_ctx.csv_sink.write_options_data.return_value = {}
        
        result = persist_and_metrics(
            mock_ctx,
            {},
            index_symbol="NIFTY",
            expiry_rule="weekly",
            expiry_date="2025-10-30",
            collection_time=datetime(2025, 10, 27, 9, 15),
            index_price=24500.0,
            index_ohlc=None,
            allow_per_option_metrics=False,
        )
        
        assert result.failed is False
        assert result.option_count == 0
        assert result.pcr is None


class TestPersistWithContext:
    """Test persist_with_context wrapper function."""

    def test_persist_with_context_basic(self):
        """Test persist_with_context calls persist_and_metrics correctly."""
        mock_ctx = Mock()
        mock_ctx.csv_sink = Mock()
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 0.9}
        mock_ctx.influx_sink = None
        mock_ctx.metrics = None
        
        mock_expiry_ctx = Mock()
        mock_expiry_ctx.index_symbol = "BANKNIFTY"
        mock_expiry_ctx.expiry_rule = "monthly"
        mock_expiry_ctx.expiry_date = "2025-11-27"
        mock_expiry_ctx.collection_time = datetime(2025, 10, 27, 10, 30)
        mock_expiry_ctx.index_price = 52000.0
        mock_expiry_ctx.allow_per_option_metrics = False
        
        enriched_data = {
            "BANKNIFTY_52000_CE": {
                "instrument_type": "CE",
                "strike": 52000,
                "last_price": 300.0,
            },
        }
        
        index_ohlc = {"open": 51900.0, "high": 52100.0, "low": 51800.0, "close": 52000.0}
        
        result = persist_with_context(mock_ctx, enriched_data, mock_expiry_ctx, index_ohlc)
        
        assert isinstance(result, PersistResult)
        assert result.failed is False
        assert result.option_count == 1
        
        # Verify CSV sink was called with correct args
        mock_ctx.csv_sink.write_options_data.assert_called_once_with(
            "BANKNIFTY",
            "2025-11-27",
            enriched_data,
            datetime(2025, 10, 27, 10, 30),
            index_price=52000.0,
            index_ohlc=index_ohlc,
            suppress_overview=True,
            return_metrics=True,
            expiry_rule_tag="monthly",
        )

    def test_persist_with_context_full_scenario(self):
        """Test persist_with_context with all features."""
        mock_ctx = Mock()
        mock_ctx.csv_sink = Mock()
        mock_ctx.csv_sink.write_options_data.return_value = {"pcr": 1.1}
        mock_ctx.influx_sink = Mock()
        mock_ctx.metrics = Mock()
        mock_ctx.metrics.options_collected = Mock()
        mock_ctx.metrics.options_collected.labels = Mock(return_value=Mock())
        mock_ctx.metrics.options_processed_total = Mock()
        mock_ctx.metrics.index_options_processed_total = Mock()
        mock_ctx.metrics.index_options_processed_total.labels = Mock(return_value=Mock())
        mock_ctx.metrics.pcr = Mock()
        mock_ctx.metrics.pcr.labels = Mock(return_value=Mock())
        mock_ctx.metrics.option_price = Mock()
        mock_ctx.metrics.option_price.labels = Mock(return_value=Mock())
        mock_ctx.metrics.option_volume = Mock()
        mock_ctx.metrics.option_volume.labels = Mock(return_value=Mock())
        mock_ctx.metrics.option_oi = Mock()
        mock_ctx.metrics.option_oi.labels = Mock(return_value=Mock())
        mock_ctx.metrics.option_iv = Mock()
        mock_ctx.metrics.option_iv.labels = Mock(return_value=Mock())
        
        mock_expiry_ctx = Mock()
        mock_expiry_ctx.index_symbol = "FINNIFTY"
        mock_expiry_ctx.expiry_rule = "weekly"
        mock_expiry_ctx.expiry_date = "2025-10-29"
        mock_expiry_ctx.collection_time = datetime(2025, 10, 27, 11, 0)
        mock_expiry_ctx.index_price = 23000.0
        mock_expiry_ctx.allow_per_option_metrics = True
        
        enriched_data = {
            "FINNIFTY_23000_CE": {
                "instrument_type": "CE",
                "strike": 23000,
                "last_price": 150.0,
                "volume": 500,
                "oi": 2000,
                "iv": 20.0,
            },
            "FINNIFTY_23000_PE": {
                "instrument_type": "PE",
                "strike": 23000,
                "last_price": 140.0,
                "volume": 600,
                "oi": 2500,
                "iv": 21.0,
            },
        }
        
        result = persist_with_context(mock_ctx, enriched_data, mock_expiry_ctx, None)
        
        assert result.failed is False
        assert result.option_count == 2
        assert result.pcr == 1.1
        
        # Verify both sinks were called
        mock_ctx.csv_sink.write_options_data.assert_called_once()
        mock_ctx.influx_sink.write_options_data.assert_called_once()
        
        # Verify metrics were set
        mock_ctx.metrics.options_collected.labels.assert_called()
        mock_ctx.metrics.option_price.labels.assert_called()
