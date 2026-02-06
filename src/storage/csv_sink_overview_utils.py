from __future__ import annotations

from typing import Any


def build_overview_row(
    *,
    ts_str: str,
    index: str,
    expiry_code: str,
    pcr: float,
    day_width: float,
    index_price: Any,
    index_net_change: float = 0.0,
    index_day_change: float = 0.0,
    vix: Any = None,
) -> tuple[list[str], list[Any]]:
    """Build header + row for the per-expiry overview CSV.

    Extracted from `CsvSink._write_overview_file`.
    Schema is intentionally stable and ordered.
    """

    pcr_values: dict[str, float] = {
        "pcr_this_week": 0.0,
        "pcr_next_week": 0.0,
        "pcr_this_month": 0.0,
        "pcr_next_month": 0.0,
    }

    key = f"pcr_{expiry_code}"
    # Preserve legacy behavior: unknown expiry codes are ignored by schema.
    if key in pcr_values:
        pcr_values[key] = float(pcr)
    else:
        pcr_values[key] = float(pcr)

    header = [
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

    row: list[Any] = [
        ts_str,
        index,
        pcr_values["pcr_this_week"],
        pcr_values["pcr_next_week"],
        pcr_values["pcr_this_month"],
        pcr_values["pcr_next_month"],
        day_width,
        float(index_price or 0.0),
        float(index_net_change),
        float(index_day_change),
        float(vix or 0.0),
    ]

    return header, row


def build_overview_snapshot_row(
    *,
    ts_str: str,
    index: str,
    pcr_snapshot: dict[str, float],
    day_width: float,
    index_price: float,
    index_net_change: float,
    index_day_change: float,
    vix: float,
    expiries_expected: int,
    expiries_collected: int,
    expected_mask: int,
    collected_mask: int,
    missing_mask: int,
) -> tuple[list[str], list[Any]]:
    """Build header + row for the aggregated overview snapshot CSV.

    Extracted from `CsvSink.write_overview_snapshot`.
    """

    header = [
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
        "expiries_expected",
        "expiries_collected",
        "expected_mask",
        "collected_mask",
        "missing_mask",
    ]

    row: list[Any] = [
        ts_str,
        index,
        pcr_snapshot.get("this_week", 0),
        pcr_snapshot.get("next_week", 0),
        pcr_snapshot.get("this_month", 0),
        pcr_snapshot.get("next_month", 0),
        day_width,
        index_price,
        index_net_change,
        index_day_change,
        vix,
        expiries_expected,
        expiries_collected,
        expected_mask,
        collected_mask,
        missing_mask,
    ]

    return header, row
