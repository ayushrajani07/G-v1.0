import csv
import logging
import os
from datetime import datetime

import pytest

from src.storage.csv_batcher import CsvBatcher


@pytest.mark.parametrize("facade_on", [True, False])
def test_csv_batcher_header_and_rows(tmp_path, monkeypatch, facade_on):
    # Toggle facade via env
    monkeypatch.setenv("G6_USE_CSVIO_FACADE", "1" if facade_on else "0")
    monkeypatch.setenv("G6_CSVIO_BACKEND", "filesystem")

    logger = logging.getLogger("test.csv_batcher")
    batcher = CsvBatcher(logger=logger, metrics=None, flush_threshold=1, verbose=True)

    out_file = tmp_path / "nifty" / "this_week" / "2025-01-01.csv"
    header = ["ts", "index", "strike", "offset", "atm"]
    rows = [
        [int(datetime.now().timestamp()), "NIFTY", 22000, 0, 22000],
        [int(datetime.now().timestamp()), "NIFTY", 22100, 100, 22000],
    ]

    key = ("NIFTY", "this_week", "2025-01-01")
    # Buffer two rows into the same file
    batcher.buffer_row(batch_key=key, filepath=str(out_file), row=rows[0], header=header)
    batcher.buffer_row(batch_key=key, filepath=str(out_file), row=rows[1], header=header)

    # Force flush
    flushed = batcher.maybe_flush_batch(batch_key=key, force_flush_env=True)
    assert flushed is True

    # Verify file contents: header once + 2 rows
    assert out_file.exists(), "Expected CSV file to be created"
    with out_file.open("r", newline="") as f:
        rdr = csv.reader(f)
        data = list(rdr)

    assert len(data) == 3, data
    assert data[0] == header, data
    assert data[1][:2] == [str(rows[0][0]), "NIFTY"]
    assert data[2][:2] == [str(rows[1][0]), "NIFTY"]
