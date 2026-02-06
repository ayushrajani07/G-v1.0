from __future__ import annotations

from src.web.dashboard.routes._csv_time_columns import rebuild_time_time_ms_from_timestamp


def test_rebuild_time_columns_no_timestamp_passthrough():
    header = "a,b"
    rows = ["1,2"]
    h2, r2 = rebuild_time_time_ms_from_timestamp(header, rows)
    assert h2 == header
    assert r2 == rows


def test_rebuild_time_columns_adds_time_and_time_ms():
    header = "timestamp,prediction"
    rows = [
        "2025-11-07 11:00:00,123.4",
        "2025-11-07T11:01:00,124.0",
    ]
    h2, r2 = rebuild_time_time_ms_from_timestamp(header, rows)
    assert h2.startswith("time,time_ms,")
    assert "timestamp" in h2
    assert len(r2) == 2
    # Ensure each row gained 2 prefix columns
    for row in r2:
        parts = row.split(",")
        assert len(parts) == 4
        assert parts[1].isdigit()  # time_ms


def test_rebuild_time_columns_rebuilds_existing_time_column():
    header = "time,timestamp,x"
    rows = ["badtime,1730977200000,ok"]
    h2, r2 = rebuild_time_time_ms_from_timestamp(header, rows)
    assert h2.startswith("time,time_ms,")
    # rebuilt row should not keep the original time value
    assert r2 and "badtime" not in r2[0]
