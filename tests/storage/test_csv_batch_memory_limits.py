from __future__ import annotations

from pathlib import Path

import pytest

from src.metrics.registry import get_registry
from src.storage.csv_sink import CsvSink


def test_csv_sink_forces_flush_when_batch_rows_exceed_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Enable batching and set a very small hard cap so we can trigger it deterministically.
    monkeypatch.setenv("G6_CSV_BATCH_FLUSH", "999999")
    monkeypatch.setenv("G6_CSV_BATCH_MAX_BUFFERED_ROWS", "3")
    monkeypatch.setenv("G6_CSV_BATCH_MAX_BUFFERED_FILES", "0")

    sink = CsvSink(base_dir=str(tmp_path))
    reg = get_registry(reset=True)
    sink.attach_metrics(reg)

    batch_key = ("NIFTY", "W0", "2026-01-26")
    option_file = str(tmp_path / "NIFTY" / "2026-01-26" / "W0_options.csv")

    header = ["ts", "x"]

    # Push 4 rows; cap is 3 so the third buffered row should force a flush.
    for i in range(4):
        sink._handle_duplicate_write_or_buffer(
            index="NIFTY",
            expiry_code="W0",
            offset=i,
            row=[f"t{i}", i],
            row_sig=("W0", i),
            option_file=option_file,
            header=header,
            file_exists=False,
            batching_enabled=True,
            batch_key=batch_key,
        )

    # Forced flush should have happened at the cap; the final row may remain buffered.
    assert sink._batch_counts.get(batch_key, 0) < 3

    # And the file should exist with header + flushed rows (at least 3).
    lines = Path(option_file).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ts,x"
    assert len(lines) >= 4
    assert "t0,0" in lines
    assert "t1,1" in lines
    assert "t2,2" in lines
