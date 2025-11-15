import csv
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, UTC

import pytest

from src.storage.csvio import api as csvio_api


@pytest.mark.serial
def test_atomic_backend_concurrent_append(tmp_path, monkeypatch):
    # Force facade + atomic backend
    monkeypatch.setenv("G6_USE_CSVIO_FACADE", "1")
    monkeypatch.setenv("G6_CSVIO_BACKEND", "atomic")

    # Prepare target file with header pre-created to avoid header races
    out_file = tmp_path / "concurrent.csv"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    header = ["thread", "idx", "ts"]
    with out_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)

    # Writer function for threads: append rows using atomic backend
    def writer_fn(tid: int, n: int = 10):
        for i in range(n):
            csvio_api.append_one(
                str(out_file),
                [tid, i, int(datetime.now(UTC).timestamp())],
                header=None,  # header already present
            )

    threads = 4
    per_thread = 10
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = [ex.submit(writer_fn, t, per_thread) for t in range(threads)]
        for f in futs:
            f.result(timeout=30)

    # Verify row count: header + threads*per_thread
    with out_file.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert rows[0] == header
    assert len(rows) == 1 + threads * per_thread, f"row_count={len(rows)} expected={1 + threads * per_thread}"