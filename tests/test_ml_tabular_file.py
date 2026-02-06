from __future__ import annotations

from src.web.dashboard.routes._tabular_file import read_header_and_rows, tail_rows


def test_read_header_and_rows_empty_file(tmp_path):
    fp = tmp_path / "x.csv"
    fp.write_text("", encoding="utf-8")
    header, rows = read_header_and_rows(fp)
    assert header == ""
    assert rows == []


def test_read_header_and_rows_splits_header(tmp_path):
    fp = tmp_path / "x.csv"
    fp.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    header, rows = read_header_and_rows(fp)
    assert header == "a,b"
    assert rows == ["1,2", "3,4"]


def test_tail_rows_behaviour():
    rows = ["r1", "r2", "r3"]
    assert tail_rows(rows, None) == ["r1", "r2", "r3"]
    assert tail_rows(rows, 2) == ["r2", "r3"]
    assert tail_rows(rows, 10) == ["r1", "r2", "r3"]
    assert tail_rows(rows, 0) == []
