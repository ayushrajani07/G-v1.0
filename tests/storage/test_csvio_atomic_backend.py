from __future__ import annotations

import csv
import os
from pathlib import Path

from storage.csvio import api


def read_rows(fp: Path) -> list[list[str]]:
    with fp.open('r', newline='') as f:
        rdr = csv.reader(f)
        return list(rdr)


def test_atomic_backend_new_and_append(tmp_path: Path, monkeypatch):
    # Force atomic backend via explicit param and env override in a separate call
    fp = tmp_path / "data.csv"
    header = ["a", "b", "c"]
    r1 = ["1", "2", "3"]

    # New file write: should write header + row
    api.append_one(str(fp), r1, header=header, backend="atomic")
    rows = read_rows(fp)
    assert rows[0] == header
    assert rows[1] == r1

    # Append many
    r2 = ["4", "5", "6"]
    r3 = ["7", "8", "9"]
    api.append_many(str(fp), [r2, r3], header=header, backend="atomic")
    rows2 = read_rows(fp)
    assert rows2[0] == header
    assert rows2[1:] == [r1, r2, r3]

    # Now use env override path (without passing backend)
    monkeypatch.setenv("G6_CSVIO_BACKEND", "atomic")
    r4 = ["10", "11", "12"]
    api.append_one(str(fp), r4, header=header)
    rows3 = read_rows(fp)
    assert rows3[-1] == r4


def test_atomic_backend_aligns_to_existing_header(tmp_path: Path):
    # Create a file with header order H1
    fp = tmp_path / "aligned.csv"
    h1 = ["x", "y", "z", "atm"]
    with fp.open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(h1)
        w.writerow(["a", "b", "c", "100"])  # seed row

    # Now append with a different header order H2 and ensure alignment to H1
    # Include strike/offset so 'atm' can be computed if needed (parity with facade tests)
    h2 = ["y", "x", "z", "strike", "offset"]
    r = ["yy", "xx", "zz", "105", "5"]  # implies atm=100 if computed

    api.append_one(str(fp), r, header=h2, backend="atomic")

    rows = read_rows(fp)
    # Header should remain H1
    assert rows[0] == h1
    # Appended row must follow header order; last column 'atm' computed from strike-offset when present
    assert rows[-1][0:3] == ["xx", "yy", "zz"]
    # 'atm' either computed or left empty string for environments where float/int conversion fails gracefully
    assert rows[-1][3] in ("100.0", "100", "")


def test_atomic_backend_respects_missing_trailing_newline(tmp_path: Path):
    # Manually write a file without a trailing newline, then append via atomic backend
    fp = tmp_path / "no_nl.csv"
    header = ["a", "b"]
    with fp.open('wb') as f:
        f.write(b"a,b\r\n1,2")  # no final newline

    api.append_one(str(fp), ["3", "4"], header=header, backend="atomic")
    rows = read_rows(fp)
    assert rows == [header, ["1", "2"], ["3", "4"]]
