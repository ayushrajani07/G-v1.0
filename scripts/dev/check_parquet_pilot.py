#!/usr/bin/env python
"""Parquet Pilot Readiness & Health Check

Runs a series of lightweight validations to confirm the Parquet pilot
is correctly configured and operational.

Checks performed:
1. pyarrow availability
2. Pilot flag enabled (G6_PARQUET_PILOT)
3. Pilot index (G6_PARQUET_INDEX) resolved
4. Base directory existence & partition layout summary
5. Storage stats (file count, total size)
6. Sample record scan (first N files) if any parquet files present

Exit codes:
0 = success (pilot enabled & readable or gracefully empty)
1 = pilot disabled
2 = pyarrow missing
3 = unexpected error

Usage:
  python scripts/dev/check_parquet_pilot.py --base-dir data/parquet --sample 3

Environment flags referenced:
  G6_PARQUET_PILOT
  G6_PARQUET_INDEX
  G6_PARQUET_PARTITION_BY
  G6_PARQUET_COMPRESSION
  G6_PARQUET_CSV_EXPORT_INTERVAL
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List

def main() -> int:
    ap = argparse.ArgumentParser(description="Parquet pilot readiness check")
    ap.add_argument("--base-dir", default="data/parquet", help="Parquet base directory")
    ap.add_argument("--sample", type=int, default=3, help="Number of parquet files to sample")
    ap.add_argument("--quiet", action="store_true", help="Suppress non-error output")
    args = ap.parse_args()

    quiet = bool(args.quiet)
    def out(msg: str) -> None:
        if not quiet:
            print(msg)

    # 1. pyarrow availability
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except Exception:
        print("ERROR: pyarrow not installed. Install with: pip install pyarrow")
        return 2

    # Late import of helpers (after path prep)
    ROOT = Path(__file__).resolve().parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    try:
        from src.storage.parquet_sink import is_parquet_enabled, get_pilot_index, ParquetSink  # type: ignore
    except Exception as e:
        print(f"ERROR: failed importing Parquet sink module: {e}")
        return 3

    enabled = False
    try:
        enabled = is_parquet_enabled()
    except Exception:
        enabled = False
    if not enabled:
        out("Parquet pilot is currently DISABLED (set G6_PARQUET_PILOT=1 to enable).")
        return 1

    # Gather config environment values
    pilot_index = get_pilot_index()
    part_cols = os.environ.get("G6_PARQUET_PARTITION_BY", "date,index,expiry")
    compression = os.environ.get("G6_PARQUET_COMPRESSION", "snappy")

    base_dir = Path(args.base_dir)
    out(f"Pilot Enabled: index={pilot_index} base_dir={base_dir} partition_by={part_cols} compression={compression}")

    if not base_dir.exists():
        out("WARNING: base directory does not exist yet (no Parquet data written).")
        return 0

    # 4. Partition layout summary: list first-level partition directories
    part_dirs: List[str] = []
    for root, dirs, files in os.walk(base_dir):
        depth = Path(root).relative_to(base_dir).parts
        # capture only directories at depth 1 (date=...) or 2 depending on partition_by order
        if len(depth) == 1:
            part_dirs.append(Path(root).name)
        if len(part_dirs) >= 12:  # cap for brevity
            break
    if part_dirs:
        out("Partitions (sample): " + ", ".join(sorted(part_dirs)))
    else:
        out("No partition directories found yet.")

    # 5. Storage stats via ParquetSink
    sink = ParquetSink(base_dir=str(base_dir))
    stats = sink.get_stats()
    out(f"Files={stats['file_count']} Size={stats['total_size_mb']:.3f}MB Compression={stats['compression']}")

    # 6. Sample read of up to N parquet files
    parquet_files: List[Path] = []
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.endswith('.parquet'):
                parquet_files.append(Path(root) / f)
        if len(parquet_files) >= args.sample:
            break
    if not parquet_files:
        out("No parquet files to sample.")
        return 0
    out(f"Sampling {min(len(parquet_files), args.sample)} parquet file(s)...")
    for fp in parquet_files[: args.sample]:
        try:
            table = pq.read_table(fp)
            out(f" {fp.name}: rows={table.num_rows} cols={table.num_columns}")
        except Exception as e:
            out(f" {fp.name}: READ ERROR {e}")

    out("Parquet pilot readiness check complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
