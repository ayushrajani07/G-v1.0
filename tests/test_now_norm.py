from __future__ import annotations

from src.web.dashboard.routes._now_norm import (
    build_realized_map_and_times,
    clamp_ms_to_rows,
    extract_now_override_raw,
    infer_now_ms_from_rows,
    nearest_time_key,
    now_and_cutoff,
    parse_int_ms,
)


def test_parse_int_ms_accepts_int_and_str():
    assert parse_int_ms(123) == 123
    assert parse_int_ms("456") == 456


def test_parse_int_ms_empty_invalid_none():
    assert parse_int_ms(None) is None
    assert parse_int_ms("") is None
    assert parse_int_ms("  ") is None
    assert parse_int_ms("nope") is None


def test_infer_now_ms_from_rows_max_ts_or_time():
    rows = [
        {"ts": "100"},
        {"time": "200"},
        {"ts": 150},
        {"ts": ""},
    ]
    assert infer_now_ms_from_rows(rows) == 200


def test_clamp_ms_to_rows():
    rows = [{"ts": 100}, {"ts": 200}]
    assert clamp_ms_to_rows(50, rows) == 100
    assert clamp_ms_to_rows(250, rows) == 200
    assert clamp_ms_to_rows(150, rows) == 150


def test_extract_now_override_raw_priority():
    qp = {"nowMs": "2", "now": "3"}
    assert extract_now_override_raw("1", qp) == "1"
    assert extract_now_override_raw(None, qp) == "2"


def test_build_realized_map_and_times_bucketed_and_non_negative():
    rows = [
        {"ts": 1000, "tp": 1.0},
        {"time": "1999", "tp": -2.0},
        {"ts": "", "tp": 3.0},
        {"ts": 2500, "tp": "x"},
    ]
    realized, ts_sorted = build_realized_map_and_times(
        rows,
        bucket_ms=1000,
        tp_getter=lambda r: r.get("tp"),
        non_negative=True,
    )
    # Second row overwrites the first after bucketing, and is clamped to 0.0
    assert realized == {1000: 0.0}
    assert ts_sorted == [1000]


def test_now_and_cutoff():
    now_ms, cutoff = now_and_cutoff([1000, 2000, 3000], window_minutes=1)
    assert now_ms == 3000
    assert cutoff == 3000 - 60_000


def test_nearest_time_key_within_tolerance():
    ts = [1000, 2000, 3000]
    assert nearest_time_key(ts, 2100, tol_ms=150) == 2000
    assert nearest_time_key(ts, 2900, tol_ms=150) == 3000
    assert nearest_time_key(ts, 2500, tol_ms=100) is None
