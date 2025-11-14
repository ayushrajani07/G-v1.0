import csv
import os
from pathlib import Path

import pytest

from storage.csvio import api


def read_csv(path: Path):
    with path.open(newline="") as f:
        rdr = csv.reader(f)
        rows = list(rdr)
    return rows


def test_append_one_writes_header_and_row(tmp_path: Path):
    p = tmp_path / "one.csv"
    api.append_one(str(p), ["v1", "v2"], header=["col1", "col2"])
    rows = read_csv(p)
    assert rows[0] == ["col1", "col2"]
    assert rows[1] == ["v1", "v2"]


def test_append_many_appends_rows_and_header_once(tmp_path: Path):
    p = tmp_path / "many.csv"
    rows_in = [["a1", "b1"], ["a2", "b2"], ["a3", "b3"]]
    api.append_many(str(p), rows_in, header=["a", "b"])
    rows = read_csv(p)
    assert rows[0] == ["a", "b"]
    assert rows[1:] == rows_in


def test_aligns_row_to_existing_header_and_computes_atm(tmp_path: Path):
    p = tmp_path / "align.csv"
    # Manually create a file with header order including 'atm' first
    file_header = ["atm", "strike", "offset", "time", "time_ms"]
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(file_header)
    # Now append using a different header (without atm); helper should align and compute atm=strike-offset
    header = ["strike", "offset", "time", "time_ms"]
    row = ["20000", "200", "2025-01-01 09:15:00", "1700000000000"]
    api.append_one(str(p), row, header=header)
    rows = read_csv(p)
    assert rows[0] == file_header
    # Check computed atm and aligned order
    assert rows[1][1] == "20000"  # strike
    assert rows[1][2] == "200"    # offset
    assert rows[1][3] == "2025-01-01 09:15:00"
    assert rows[1][4] == "1700000000000"
    # atm computed as float(strike) - int(offset) => 19800.0 cast back to string by csv
    assert rows[1][0] in ("19800.0", "19800")
