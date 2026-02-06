from __future__ import annotations

from src.storage.csv_sink_row_utils import align_row_to_header, reorder_time_columns


def test_reorder_time_columns_pure_moves_to_end_for_new_file():
    header = [
        "timestamp",
        "index",
        "expiry_tag",
        "time",
        "expiry_date",
        "time_ms",
        "offset",
    ]
    row = [
        "12-11-2025 09:30:00",
        "NIFTY",
        "this_week",
        "2025-11-12T09:30:00+05:30",
        "2025-11-20",
        1731381000000,
        0,
    ]

    new_header, new_row = reorder_time_columns(header[:], row[:], file_exists=False)

    assert new_header[-2:] == ["time", "time_ms"]
    assert new_row[-2:] == ["2025-11-12T09:30:00+05:30", 1731381000000]
    assert new_header[:3] == ["timestamp", "index", "expiry_tag"]


def test_reorder_time_columns_pure_keeps_existing_schema():
    header = ["timestamp", "time", "index", "time_ms", "offset"]
    row = ["ts", "iso", "NIFTY", 123, 0]

    same_header, same_row = reorder_time_columns(header[:], row[:], file_exists=True)
    assert same_header == header
    assert same_row == row


def test_align_row_to_header_pure_atm_derivation_and_placeholders():
    file_header = [
        "timestamp",
        "index",
        "expiry_tag",
        "expiry_date",
        "offset",
        "index_price",
        "strike",
        "atm",
        "ce",
        "pe",
        "extra_col",
    ]
    header = [
        "timestamp",
        "index",
        "expiry_tag",
        "expiry_date",
        "offset",
        "index_price",
        "strike",
        "ce",
        "pe",
    ]
    row = [
        "12-11-2025 09:30:00",
        "NIFTY",
        "this_week",
        "2025-11-20",
        50,
        24580.0,
        24600.0,
        92.0,
        108.0,
    ]

    aligned = align_row_to_header(file_header, row, header)

    assert len(aligned) == len(file_header)
    assert aligned[file_header.index("atm")] == 24600.0 - 50.0
    assert aligned[file_header.index("extra_col")] == ""
    assert aligned[file_header.index("ce")] == 92.0
    assert aligned[file_header.index("pe")] == 108.0
