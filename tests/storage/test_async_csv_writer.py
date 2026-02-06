from __future__ import annotations

from pathlib import Path

from src.storage.async_csv_writer import AsyncCsvWriter


def test_async_csv_writer_writes_header_and_rows(tmp_path: Path) -> None:
    w = AsyncCsvWriter(str(tmp_path), max_queue_size=50, buffer_size=0, flush_interval_seconds=0.01)
    try:
        w.append_row("x.csv", [1, 2], header=["a", "b"])
        w.append_many_rows("x.csv", [[3, 4], [5, 6]], header=None)
        w.close()
    finally:
        # close() is idempotent in practice; call again to ensure no exception
        try:
            w.close()
        except Exception:
            pass

    data = (tmp_path / "x.csv").read_text(encoding="utf-8").splitlines()
    assert data[0] == "a,b"
    assert data[1] == "1,2"
    assert data[2] == "3,4"
    assert data[3] == "5,6"
