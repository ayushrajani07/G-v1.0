import csv
import logging
import os
from datetime import datetime

import pytest

from src.storage.csv_aggregator import CsvAggregator


@pytest.mark.parametrize("facade_on", [True, False])
def test_csv_aggregator_overview_header_and_row(tmp_path, monkeypatch, facade_on):
    # Toggle facade via env
    monkeypatch.setenv("G6_USE_CSVIO_FACADE", "1" if facade_on else "0")
    monkeypatch.setenv("G6_CSVIO_BACKEND", "filesystem")

    base_dir = str(tmp_path)
    logger = logging.getLogger("test.csv_aggregator")
    agg = CsvAggregator(base_dir=base_dir, logger=logger, metrics=None, overview_interval_seconds=1)

    # Inject index price context used by writer
    agg.inject_last_prices(index="NIFTY", index_price=100.0, index_open=95.0, vix=12.0)

    ts = datetime.now()
    pcr_snapshot = {
        "this_week": 1.2,
        "this_month": 1.0,
    }

    # Write snapshot
    agg.write_overview_snapshot(
        index="NIFTY",
        pcr_snapshot=pcr_snapshot,
        timestamp=ts,
        day_width=0.5,
        expected_expiries=["this_week", "this_month"],
        vix=12.0,
    )

    # Verify file exists and has header + one data row
    out_file = os.path.join(base_dir, "overview", "NIFTY", f"{ts.strftime('%Y-%m-%d')}.csv")
    assert os.path.isfile(out_file), out_file

    with open(out_file, "r", newline="", encoding="utf-8") as f:
        rdr = csv.reader(f)
        rows = list(rdr)

    assert len(rows) == 2, rows
    header = rows[0]
    assert header[0:2] == ["timestamp", "index"], header

    # Append again and ensure header not duplicated
    agg.write_overview_snapshot(
        index="NIFTY",
        pcr_snapshot=pcr_snapshot,
        timestamp=datetime.now(),
        day_width=0.5,
        expected_expiries=["this_week", "this_month"],
        vix=12.0,
    )

    with open(out_file, "r", newline="", encoding="utf-8") as f:
        rdr = csv.reader(f)
        rows2 = list(rdr)

    assert len(rows2) == 3, rows2
    assert rows2[0] == header
