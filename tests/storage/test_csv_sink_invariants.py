import csv
import datetime as _dt
from pathlib import Path

from src.storage.csv_sink import CsvSink


def _option(*, instrument_type: str, strike: float, expiry_date: _dt.date) -> dict:
    return {
        "instrument_type": instrument_type,
        "strike": strike,
        "last_price": 100.0,
        "avg_price": 100.0,
        "volume": 10,
        "oi": 10,
        "expiry_date": expiry_date.strftime("%Y-%m-%d"),
    }


def _options_pair(*, strike: float, expiry_date: _dt.date) -> dict[str, dict]:
    return {
        f"CE_{strike}": _option(instrument_type="CE", strike=strike, expiry_date=expiry_date),
        f"PE_{strike}": _option(instrument_type="PE", strike=strike, expiry_date=expiry_date),
    }


def _read_csv_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_csv_sink_headers_and_row_alignment(tmp_path: Path) -> None:
    base_dir = tmp_path / "data"
    sink = CsvSink(base_dir=str(base_dir))

    index = "SENSEX"
    expiry_date = _dt.date(2026, 2, 10)
    ts1 = _dt.datetime(2026, 2, 7, 9, 15, 0)
    ts2 = _dt.datetime(2026, 2, 7, 9, 15, 31)

    options_data = _options_pair(strike=100.0, expiry_date=expiry_date)

    sink.write_options_data(
        index,
        expiry_date,
        options_data,
        ts1,
        index_price=100.0,
        expiry_rule_tag="this_week",
        suppress_overview=False,
    )
    sink.write_options_data(
        index,
        expiry_date,
        options_data,
        ts2,
        index_price=100.0,
        expiry_rule_tag="this_week",
        suppress_overview=False,
    )

    date_str = ts1.strftime("%Y-%m-%d")
    overview_file = base_dir / "overview" / index / f"{date_str}.csv"
    option_file = base_dir / index / "this_week" / "0" / f"{date_str}.csv"

    assert overview_file.exists(), "expected overview file"
    assert option_file.exists(), "expected option file"

    for fp in (overview_file, option_file):
        rows = _read_csv_rows(fp)
        assert len(rows) >= 2, f"expected header + at least one data row in {fp}"
        header = rows[0]
        assert header, f"expected non-empty header row in {fp}"
        # Header should not be duplicated as a later row, and all rows should align.
        for r in rows[1:]:
            assert r != header, f"unexpected duplicate header row in {fp}"
            assert len(r) == len(header), f"row/header length mismatch in {fp}"


def test_csv_sink_duplicate_suppression_same_timestamp(tmp_path: Path) -> None:
    base_dir = tmp_path / "data"
    sink = CsvSink(base_dir=str(base_dir))

    index = "SENSEX"
    expiry_date = _dt.date(2026, 2, 10)
    ts = _dt.datetime(2026, 2, 7, 9, 15, 0)

    options_data = _options_pair(strike=100.0, expiry_date=expiry_date)

    sink.write_options_data(
        index,
        expiry_date,
        options_data,
        ts,
        index_price=100.0,
        expiry_rule_tag="this_week",
        suppress_overview=True,
    )

    date_str = ts.strftime("%Y-%m-%d")
    option_file = base_dir / index / "this_week" / "0" / f"{date_str}.csv"
    assert option_file.exists(), "expected option file"

    rows_before = _read_csv_rows(option_file)

    # Same logical row at the same timestamp should not double-append.
    sink.write_options_data(
        index,
        expiry_date,
        options_data,
        ts,
        index_price=100.0,
        expiry_rule_tag="this_week",
        suppress_overview=True,
    )

    rows_after = _read_csv_rows(option_file)
    assert rows_after == rows_before
