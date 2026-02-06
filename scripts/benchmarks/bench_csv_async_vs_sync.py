from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Ensure repo root is on sys.path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.storage.async_csv_writer import AsyncCsvWriter
from src.storage.csv_writer import CsvWriter


@dataclass(frozen=True)
class Stats:
    label: str
    seconds: float
    rows_written: int
    rows_per_s: float
    mean_batch_ms: float
    p95_batch_ms: float


def _pctl(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    k = int(max(0, min(len(vals) - 1, round((p / 100.0) * (len(vals) - 1)))))
    return vals[k]


def _make_rows(n: int, cols: int, seed: int = 1337) -> list[list[object]]:
    rng = random.Random(seed)
    rows: list[list[object]] = []
    for i in range(n):
        row: list[object] = [i, time.time()]
        for _ in range(max(0, cols - 2)):
            row.append(rng.random())
        rows.append(row)
    return rows


def _bench_writer(writer, *, rel_path: str, header: list[str], rows: list[list[object]], batch_size: int) -> Stats:
    batch_lat: list[float] = []
    t0 = time.perf_counter()
    first = True
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        b0 = time.perf_counter()
        writer.append_many_rows(rel_path, batch, header if first else None)
        b1 = time.perf_counter()
        batch_lat.append(b1 - b0)
        first = False
    # Flush/close when supported
    if hasattr(writer, "flush"):
        try:
            writer.flush()
        except Exception:
            pass
    if hasattr(writer, "close"):
        try:
            writer.close()
        except Exception:
            pass
    t1 = time.perf_counter()

    total_s = t1 - t0
    mean_ms = statistics.mean(batch_lat) * 1000.0 if batch_lat else 0.0
    p95_ms = _pctl(batch_lat, 95) * 1000.0
    return Stats(
        label=type(writer).__name__,
        seconds=total_s,
        rows_written=len(rows),
        rows_per_s=(len(rows) / total_s) if total_s > 0 else 0.0,
        mean_batch_ms=mean_ms,
        p95_batch_ms=p95_ms,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare sync CsvWriter vs AsyncCsvWriter throughput")
    ap.add_argument("--out-dir", default=os.path.join("_tmp", "csv_bench"), help="Output directory")
    ap.add_argument("--rows", type=int, default=10000, help="Rows per run")
    ap.add_argument("--cols", type=int, default=12, help="Columns per row")
    ap.add_argument("--batch-size", type=int, default=100, help="Rows per append_many_rows")
    ap.add_argument("--async-queue", type=int, default=5000, help="Async queue size")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    header = [f"c{i}" for i in range(args.cols)]
    rows = _make_rows(args.rows, args.cols)

    sync_base = out_dir / "sync"
    async_base = out_dir / "async"
    sync_base.mkdir(parents=True, exist_ok=True)
    async_base.mkdir(parents=True, exist_ok=True)

    sync_file = sync_base / "writer.csv"
    async_file = async_base / "writer.csv"
    for fp in (sync_file, async_file):
        try:
            fp.unlink()
        except FileNotFoundError:
            pass

    sync_writer = CsvWriter(str(sync_base))
    s1 = _bench_writer(sync_writer, rel_path="writer.csv", header=header, rows=rows, batch_size=max(1, args.batch_size))

    async_writer = AsyncCsvWriter(str(async_base), max_queue_size=max(1, args.async_queue), flush_interval_seconds=0.01)
    s2 = _bench_writer(async_writer, rel_path="writer.csv", header=header, rows=rows, batch_size=max(1, args.batch_size))

    def _fmt(s: Stats) -> str:
        return (
            f"{s.label}: {s.rows_written} rows in {s.seconds:.3f}s "
            f"({s.rows_per_s:,.0f} rows/s) mean_batch={s.mean_batch_ms:.3f}ms p95_batch={s.p95_batch_ms:.3f}ms"
        )

    print(_fmt(s1))
    print(_fmt(s2))
    if s1.seconds > 0 and s2.seconds > 0:
        print(f"speedup_async_vs_sync: {s1.seconds / s2.seconds:.3f}x")

    print(f"files: {sync_file} ; {async_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
