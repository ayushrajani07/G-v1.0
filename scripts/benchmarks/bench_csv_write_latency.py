from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.storage.csvio import api as csvio


@dataclass(frozen=True)
class Stats:
    count: int
    total_s: float
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    rows_per_s: float


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return values[0]
    if p >= 100:
        return values[-1]
    k = (len(values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def _compute_stats(latencies_s: list[float], *, rows_written: int) -> Stats:
    lat_sorted = sorted(latencies_s)
    total_s = sum(lat_sorted)
    mean_ms = (total_s / len(lat_sorted) * 1000.0) if lat_sorted else 0.0
    median_ms = statistics.median(lat_sorted) * 1000.0 if lat_sorted else 0.0
    p95_ms = _percentile(lat_sorted, 95) * 1000.0
    p99_ms = _percentile(lat_sorted, 99) * 1000.0
    min_ms = lat_sorted[0] * 1000.0 if lat_sorted else 0.0
    max_ms = lat_sorted[-1] * 1000.0 if lat_sorted else 0.0
    rows_per_s = (rows_written / total_s) if total_s > 0 else 0.0
    return Stats(
        count=len(lat_sorted),
        total_s=total_s,
        mean_ms=mean_ms,
        median_ms=median_ms,
        p95_ms=p95_ms,
        p99_ms=p99_ms,
        min_ms=min_ms,
        max_ms=max_ms,
        rows_per_s=rows_per_s,
    )


def _format_stats(name: str, s: Stats) -> str:
    return (
        f"{name}: count={s.count} total={s.total_s:.3f}s "
        f"mean={s.mean_ms:.3f}ms median={s.median_ms:.3f}ms "
        f"p95={s.p95_ms:.3f}ms p99={s.p99_ms:.3f}ms "
        f"min={s.min_ms:.3f}ms max={s.max_ms:.3f}ms "
        f"throughput={s.rows_per_s:,.1f} rows/s"
    )


def _make_rows(*, rows: int, cols: int) -> list[list[object]]:
    rng = random.Random(1337)
    out: list[list[object]] = []
    for i in range(rows):
        row: list[object] = [i, time.time()]
        for _ in range(max(0, cols - 2)):
            row.append(rng.random())
        out.append(row)
    return out


def _bench_append_one(
    *,
    filepath: str,
    header: list[str],
    rows: Iterable[list[object]],
    backend: str,
) -> tuple[list[float], int]:
    latencies: list[float] = []
    rows_written = 0
    first = True
    for row in rows:
        t0 = time.perf_counter()
        csvio.append_one(filepath, list(row), header if first else None, backend=backend)
        t1 = time.perf_counter()
        latencies.append(t1 - t0)
        rows_written += 1
        first = False
    return latencies, rows_written


def _bench_append_many(
    *,
    filepath: str,
    header: list[str],
    rows: list[list[object]],
    batch_size: int,
    backend: str,
) -> tuple[list[float], int]:
    latencies: list[float] = []
    rows_written = 0
    first = True
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        t0 = time.perf_counter()
        csvio.append_many(filepath, batch, header if first else None, backend=backend)
        t1 = time.perf_counter()
        latencies.append(t1 - t0)
        rows_written += len(batch)
        first = False
    return latencies, rows_written


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile CSV append latency (current implementation)")
    parser.add_argument("--out-dir", default=os.path.join("_tmp", "csv_bench"), help="Output directory")
    parser.add_argument("--rows", type=int, default=2000, help="Number of rows to write")
    parser.add_argument("--cols", type=int, default=12, help="Number of columns per row")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for append_many")
    parser.add_argument(
        "--backend",
        default="filesystem",
        choices=["filesystem", "atomic"],
        help="csvio backend (respects G6_CSVIO_BACKEND if set)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    header = [f"c{i}" for i in range(args.cols)]
    rows = _make_rows(rows=args.rows, cols=args.cols)

    file_one = str(out_dir / f"append_one_{args.backend}.csv")
    file_many = str(out_dir / f"append_many_{args.backend}.csv")

    # Clean outputs to keep measurements stable
    for fp in (file_one, file_many):
        try:
            os.remove(fp)
        except FileNotFoundError:
            pass

    lat_one, n_one = _bench_append_one(filepath=file_one, header=header, rows=rows, backend=args.backend)
    s_one = _compute_stats(lat_one, rows_written=n_one)

    lat_many, n_many = _bench_append_many(
        filepath=file_many,
        header=header,
        rows=rows,
        batch_size=max(1, int(args.batch_size)),
        backend=args.backend,
    )
    s_many_batches = _compute_stats(lat_many, rows_written=n_many)

    # Per-row estimate for batched writes (batch latency / rows in that batch)
    per_row_many: list[float] = []
    for dt, start in zip(lat_many, range(0, len(rows), max(1, int(args.batch_size))), strict=False):
        batch_len = min(max(1, int(args.batch_size)), len(rows) - start)
        per_row_many.append(dt / batch_len)
    s_many_rows = _compute_stats(per_row_many, rows_written=n_many)

    print(_format_stats("append_one (per-row)", s_one))
    print(_format_stats("append_many (per-batch)", s_many_batches))
    print(_format_stats("append_many (per-row est.)", s_many_rows))
    print(f"files: {file_one} ; {file_many}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
