from __future__ import annotations

from src.storage.csv_sink_overview_utils import build_overview_row, build_overview_snapshot_row


def test_build_overview_row_sets_only_target_expiry_pcr():
    header, row = build_overview_row(
        ts_str="12-11-2025 09:30:00",
        index="NIFTY",
        expiry_code="this_week",
        pcr=0.92,
        day_width=100.5,
        index_price=24550.0,
        index_net_change=10.0,
        index_day_change=5.0,
        vix=None,
    )

    assert header == [
        "timestamp",
        "index",
        "pcr_this_week",
        "pcr_next_week",
        "pcr_this_month",
        "pcr_next_month",
        "day_width",
        "index_price",
        "index_net_change",
        "index_day_change",
        "VIX",
    ]

    d = dict(zip(header, row))
    assert d["pcr_this_week"] == 0.92
    assert d["pcr_next_week"] == 0.0
    assert d["pcr_this_month"] == 0.0
    assert d["pcr_next_month"] == 0.0
    assert d["index_price"] == 24550.0
    assert d["VIX"] == 0.0


def test_build_overview_row_handles_falsey_values_like_legacy():
    # Mirrors legacy `float(index_price or 0.0)` / `float(vix or 0.0)` behavior.
    header, row = build_overview_row(
        ts_str="x",
        index="NIFTY",
        expiry_code="this_week",
        pcr=1.0,
        day_width=0.0,
        index_price=None,
        vix=0.0,
    )
    d = dict(zip(header, row))
    assert d["index_price"] == 0.0
    assert d["VIX"] == 0.0


def test_build_overview_snapshot_row_schema_and_values():
    header, row = build_overview_snapshot_row(
        ts_str="12-11-2025 10:00:00",
        index="NIFTY",
        pcr_snapshot={"this_week": 0.91, "next_week": 1.02},
        day_width=200.0,
        index_price=24600.0,
        index_net_change=15.0,
        index_day_change=7.0,
        vix=12.3,
        expiries_expected=4,
        expiries_collected=2,
        expected_mask=0b1111,
        collected_mask=0b0011,
        missing_mask=0b1100,
    )

    assert header[:6] == [
        "timestamp",
        "index",
        "pcr_this_week",
        "pcr_next_week",
        "pcr_this_month",
        "pcr_next_month",
    ]

    d = dict(zip(header, row))
    assert d["pcr_this_week"] == 0.91
    assert d["pcr_next_week"] == 1.02
    assert d["pcr_this_month"] == 0
    assert d["pcr_next_month"] == 0
    assert d["missing_mask"] == 0b1100
