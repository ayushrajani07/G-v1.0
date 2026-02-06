from __future__ import annotations

from src.web.dashboard.core.csv_io import parse_time_epoch_ms


def test_parse_time_epoch_ms_numeric_seconds():
    assert parse_time_epoch_ms("1700000000") == 1700000000 * 1000


def test_parse_time_epoch_ms_numeric_milliseconds():
    assert parse_time_epoch_ms("1700000000123") == 1700000000123


def test_parse_time_epoch_ms_numeric_milliseconds_longer_string():
    # Some dashboards append extra digits; ensure we keep ms resolution
    assert parse_time_epoch_ms("1700000000123456") == 1700000000123


def test_parse_time_epoch_ms_empty_returns_none():
    assert parse_time_epoch_ms("") is None
