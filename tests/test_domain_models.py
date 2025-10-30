"""Tests for domain.models module."""
from __future__ import annotations

import datetime as dt
import pytest

from src.domain.models import (
    OptionQuote,
    EnrichedOption,
    ExpirySnapshot,
    OverviewSnapshot,
    _parse_ts,
)


# ========== Original Tests (Kept) ==========

def test_option_quote_from_raw_basic():
    raw = {"last_price": 123.45, "volume": 10, "oi": 200, "timestamp": "2025-09-26T10:15:30Z"}
    q = OptionQuote.from_raw("NFO:ABC123CE", raw)
    assert q.symbol == "ABC123CE"
    assert q.exchange == "NFO"
    assert q.last_price == 123.45
    assert q.volume == 10 and q.oi == 200
    assert isinstance(q.timestamp, dt.datetime)


def test_enriched_option_from_quote():
    raw = {"last_price": 10, "volume": 1, "oi": 5, "timestamp": "2025-09-26T10:15:30Z"}
    q = OptionQuote.from_raw("NFO:XYZ999PE", raw)
    enriched = EnrichedOption.from_quote(q, {"iv": 25.4, "delta": 0.55, "gamma": 0.01, "theta": -5.2, "vega": 12.3})
    assert enriched.iv == 25.4
    assert enriched.delta == 0.55
    assert enriched.raw is q.raw


def test_expiry_snapshot_option_count():
    now = dt.datetime.now(dt.timezone.utc)
    q1 = OptionQuote.from_raw("NFO:A1CE", {"last_price": 1})
    q2 = OptionQuote.from_raw("NFO:A2PE", {"last_price": 2})
    snap = ExpirySnapshot(index="NIFTY", expiry_rule="this_week", expiry_date=now.date(), atm_strike=100.0, options=[q1, q2], generated_at=now)
    assert snap.option_count == 2


# ========== New Comprehensive Tests ==========

class TestParseTimestamp:
    """Test _parse_ts timestamp parsing function."""

    def test_parse_ts_iso8601_formats(self):
        """Test various ISO8601 formats."""
        # With microseconds and Z
        ts1 = _parse_ts("2025-10-27T09:15:30.123456Z")
        assert ts1 is not None and ts1.year == 2025
        
        # With timezone offset
        ts2 = _parse_ts("2025-10-27T09:15:30+05:30")
        assert ts2 is not None
        
        # Without microseconds
        ts3 = _parse_ts("2025-10-27T09:15:30Z")
        assert ts3 is not None

    def test_parse_ts_edge_cases(self):
        """Test edge cases for timestamp parsing."""
        assert _parse_ts("") is None
        assert _parse_ts("invalid") is None
        assert _parse_ts("2025-99-99") is None


class TestOptionQuoteExtended:
    """Extended tests for OptionQuote."""

    def test_from_raw_without_exchange(self):
        """Test defaults to NSE when no exchange prefix."""
        q = OptionQuote.from_raw("NIFTY24500CE", {"last_price": 100.0})
        assert q.exchange == "NSE"
        assert q.symbol == "NIFTY24500CE"

    def test_from_raw_with_ltp_field(self):
        """Test 'ltp' field as alternative to 'last_price'."""
        q = OptionQuote.from_raw("NSE:TEST", {"ltp": 110.0})
        assert q.last_price == 110.0

    def test_from_raw_with_ts_field(self):
        """Test 'ts' field as alternative to 'timestamp'."""
        q = OptionQuote.from_raw("NSE:TEST", {"last_price": 100.0, "ts": "2025-10-27T10:30:00Z"})
        assert q.timestamp is not None
        assert q.timestamp.hour == 10

    def test_from_raw_missing_optional_fields(self):
        """Test handles missing fields with defaults."""
        q = OptionQuote.from_raw("NSE:TEST", {})
        assert q.last_price == 0.0
        assert q.volume == 0
        assert q.oi == 0

    def test_from_raw_none_values(self):
        """Test handles None values gracefully."""
        q = OptionQuote.from_raw("NSE:TEST", {"last_price": None, "volume": None})
        assert q.last_price == 0.0
        assert q.volume == 0

    def test_as_dict_with_timestamp(self):
        """Test serialization with timestamp."""
        ts = dt.datetime(2025, 10, 27, 9, 15, 30, tzinfo=dt.UTC)
        q = OptionQuote("NIFTY24500CE", "NSE", 120.5, timestamp=ts)
        result = q.as_dict()
        assert result["timestamp"].endswith("Z")

    def test_as_dict_without_timestamp(self):
        """Test serialization without timestamp."""
        q = OptionQuote("NIFTY24500CE", "NSE", 120.5)
        result = q.as_dict()
        assert result["timestamp"] is None

    def test_raw_field_preservation(self):
        """Test raw data is preserved."""
        raw = {"custom": "value", "last_price": 100.0}
        q = OptionQuote.from_raw("NSE:TEST", raw)
        assert q.raw["custom"] == "value"


class TestEnrichedOptionExtended:
    """Extended tests for EnrichedOption."""

    def test_from_quote_with_all_greeks(self):
        """Test enrichment with all Greek values."""
        q = OptionQuote("NIFTY24500CE", "NSE", 120.5)
        enriched = EnrichedOption.from_quote(q, {
            "iv": 18.5,
            "delta": 0.45,
            "gamma": 0.002,
            "theta": -12.5,
            "vega": 25.0,
        })
        assert enriched.iv == 18.5
        assert enriched.delta == 0.45
        assert enriched.gamma == 0.002
        assert enriched.theta == -12.5
        assert enriched.vega == 25.0

    def test_from_quote_partial_greeks(self):
        """Test enrichment with partial Greek values."""
        q = OptionQuote("NIFTY24500CE", "NSE", 120.5)
        enriched = EnrichedOption.from_quote(q, {"iv": 20.0})
        assert enriched.iv == 20.0
        assert enriched.delta is None
        assert enriched.gamma is None

    def test_inherits_base_fields(self):
        """Test EnrichedOption preserves base OptionQuote fields."""
        q = OptionQuote("NIFTY24500PE", "NSE", 95.0, volume=800, oi=4000)
        enriched = EnrichedOption.from_quote(q, {"iv": 19.2})
        assert enriched.symbol == "NIFTY24500PE"
        assert enriched.last_price == 95.0
        assert enriched.volume == 800
        assert enriched.oi == 4000


class TestExpirySnapshotExtended:
    """Extended tests for ExpirySnapshot."""

    def test_as_dict_complete(self):
        """Test complete serialization."""
        options = [OptionQuote("OPT1", "NSE", 100.0, volume=1000, oi=5000)]
        snap = ExpirySnapshot(
            index="NIFTY",
            expiry_rule="weekly",
            expiry_date=dt.date(2025, 10, 30),
            atm_strike=24500.0,
            options=options,
            generated_at=dt.datetime(2025, 10, 27, 9, 15, 0, tzinfo=dt.UTC),
        )
        result = snap.as_dict()
        assert result["index"] == "NIFTY"
        assert result["expiry_rule"] == "weekly"
        assert result["expiry_date"] == "2025-10-30"
        assert result["atm_strike"] == 24500.0
        assert result["option_count"] == 1
        assert len(result["options"]) == 1

    def test_as_dict_empty_options(self):
        """Test serialization with no options."""
        snap = ExpirySnapshot(
            index="FINNIFTY",
            expiry_rule="weekly",
            expiry_date=dt.date(2025, 10, 29),
            atm_strike=23000.0,
            options=[],
            generated_at=dt.datetime.now(dt.UTC),
        )
        result = snap.as_dict()
        assert result["option_count"] == 0
        assert result["options"] == []


class TestOverviewSnapshot:
    """Test OverviewSnapshot dataclass."""

    def test_from_expiry_snapshots_multi_index(self):
        """Test overview from multiple indices."""
        snap1 = ExpirySnapshot(
            index="NIFTY",
            expiry_rule="weekly",
            expiry_date=dt.date(2025, 10, 30),
            atm_strike=24500.0,
            options=[
                OptionQuote("NIFTY24500CE", "NSE", 120.5),
                OptionQuote("NIFTY24500PE", "NSE", 95.0),
            ],
            generated_at=dt.datetime.now(dt.UTC),
        )
        snap2 = ExpirySnapshot(
            index="BANKNIFTY",
            expiry_rule="monthly",
            expiry_date=dt.date(2025, 11, 27),
            atm_strike=52000.0,
            options=[
                OptionQuote("BANKNIFTY52000CE", "NSE", 300.0),
                OptionQuote("BANKNIFTY52000PE", "NSE", 280.0),
            ],
            generated_at=dt.datetime.now(dt.UTC),
        )
        
        overview = OverviewSnapshot.from_expiry_snapshots([snap1, snap2])
        assert overview.total_indices == 2
        assert overview.total_expiries == 2
        assert overview.total_options == 4
        assert overview.put_call_ratio == 1.0  # 2 CE, 2 PE

    def test_from_expiry_snapshots_pcr_calculation(self):
        """Test PCR calculation."""
        options = [
            OptionQuote("OPT1CE", "NSE", 100.0),
            OptionQuote("OPT2CE", "NSE", 110.0),
            OptionQuote("OPT3CE", "NSE", 120.0),
            OptionQuote("OPT4PE", "NSE", 90.0),
            OptionQuote("OPT5PE", "NSE", 95.0),
        ]
        snap = ExpirySnapshot(
            index="NIFTY",
            expiry_rule="weekly",
            expiry_date=dt.date(2025, 10, 30),
            atm_strike=24500.0,
            options=options,
            generated_at=dt.datetime.now(dt.UTC),
        )
        overview = OverviewSnapshot.from_expiry_snapshots([snap])
        # 3 calls, 2 puts => PCR = 2/3
        assert overview.put_call_ratio is not None
        assert abs(overview.put_call_ratio - 0.667) < 0.01

    def test_from_expiry_snapshots_no_calls(self):
        """Test PCR when no calls present."""
        options = [OptionQuote("OPT1PE", "NSE", 95.0)]
        snap = ExpirySnapshot(
            index="NIFTY",
            expiry_rule="weekly",
            expiry_date=dt.date(2025, 10, 30),
            atm_strike=24500.0,
            options=options,
            generated_at=dt.datetime.now(dt.UTC),
        )
        overview = OverviewSnapshot.from_expiry_snapshots([snap])
        assert overview.put_call_ratio is None

    def test_from_expiry_snapshots_max_pain(self):
        """Test max pain (ATM average) calculation."""
        snap1 = ExpirySnapshot(
            index="NIFTY",
            expiry_rule="weekly",
            expiry_date=dt.date(2025, 10, 30),
            atm_strike=24000.0,
            options=[],
            generated_at=dt.datetime.now(dt.UTC),
        )
        snap2 = ExpirySnapshot(
            index="NIFTY",
            expiry_rule="monthly",
            expiry_date=dt.date(2025, 11, 27),
            atm_strike=26000.0,
            options=[],
            generated_at=dt.datetime.now(dt.UTC),
        )
        overview = OverviewSnapshot.from_expiry_snapshots([snap1, snap2])
        assert overview.max_pain_strike == 25000.0  # Average of 24000 and 26000

    def test_from_expiry_snapshots_empty(self):
        """Test with empty snapshots list."""
        overview = OverviewSnapshot.from_expiry_snapshots([])
        assert overview.total_indices == 0
        assert overview.total_expiries == 0
        assert overview.total_options == 0
        assert overview.put_call_ratio is None
        assert overview.max_pain_strike is None

    def test_from_expiry_snapshots_unique_indices(self):
        """Test counts unique indices correctly."""
        snap1 = ExpirySnapshot(
            index="NIFTY",
            expiry_rule="weekly",
            expiry_date=dt.date(2025, 10, 30),
            atm_strike=24500.0,
            options=[],
            generated_at=dt.datetime.now(dt.UTC),
        )
        snap2 = ExpirySnapshot(
            index="NIFTY",
            expiry_rule="monthly",
            expiry_date=dt.date(2025, 11, 27),
            atm_strike=25000.0,
            options=[],
            generated_at=dt.datetime.now(dt.UTC),
        )
        overview = OverviewSnapshot.from_expiry_snapshots([snap1, snap2])
        assert overview.total_indices == 1  # Only NIFTY
        assert overview.total_expiries == 2

    def test_as_dict_complete(self):
        """Test overview serialization."""
        overview = OverviewSnapshot(
            generated_at=dt.datetime(2025, 10, 27, 9, 15, 30, tzinfo=dt.UTC),
            total_indices=4,
            total_expiries=12,
            total_options=240,
            put_call_ratio=0.92,
            max_pain_strike=24500.0,
        )
        result = overview.as_dict()
        assert result["total_indices"] == 4
        assert result["total_expiries"] == 12
        assert result["total_options"] == 240
        assert result["put_call_ratio"] == 0.92
        assert result["max_pain_strike"] == 24500.0
        assert result["generated_at"].endswith("Z")

    def test_as_dict_with_nulls(self):
        """Test serialization with None values."""
        overview = OverviewSnapshot(
            generated_at=dt.datetime.now(dt.UTC),
            total_indices=0,
            total_expiries=0,
            total_options=0,
            put_call_ratio=None,
            max_pain_strike=None,
        )
        result = overview.as_dict()
        assert result["put_call_ratio"] is None
        assert result["max_pain_strike"] is None
