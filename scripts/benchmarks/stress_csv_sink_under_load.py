from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure repo root is on sys.path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.storage.csv_sink import CsvSink


def main() -> int:
    ap = argparse.ArgumentParser(description="Stress CsvSink batching/async writer under load")
    ap.add_argument("--out-dir", default=os.path.join("_tmp", "csv_stress"), help="Base output directory")
    ap.add_argument("--rows", type=int, default=50000, help="Rows to buffer/write")
    ap.add_argument("--batch-flush", type=int, default=200, help="G6_CSV_BATCH_FLUSH threshold")
    ap.add_argument("--max-buffered-rows", type=int, default=2000, help="G6_CSV_BATCH_MAX_BUFFERED_ROWS")
    ap.add_argument("--async-writer", action="store_true", help="Enable AsyncCsvWriter via env")
    args = ap.parse_args()

    # Configure sink behavior via env (keeps this a true integration path)
    os.environ["G6_CSV_BATCH_FLUSH"] = str(int(args.batch_flush))
    os.environ["G6_CSV_BATCH_MAX_BUFFERED_ROWS"] = str(int(args.max_buffered_rows))
    os.environ["G6_CSV_BATCH_MAX_BUFFERED_FILES"] = "0"
    if args.async_writer:
        os.environ["G6_CSV_ASYNC_WRITER"] = "1"
    else:
        os.environ.pop("G6_CSV_ASYNC_WRITER", None)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sink = CsvSink(base_dir=str(out_dir))

    batch_key = ("NIFTY", "W0", "2026-01-26")
    option_file = str(out_dir / "NIFTY" / "2026-01-26" / "W0_options.csv")
    header = ["ts", "x"]

    t0 = time.perf_counter()
    for i in range(int(args.rows)):
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

    # Force final flush
    sink._maybe_flush_batch(batching_enabled=True, batch_key=batch_key, force_flush=True)

    # Flush async writer if enabled
    if getattr(sink, "writer", None) is not None and hasattr(sink.writer, "close"):
        try:
            sink.writer.close()  # type: ignore[attr-defined]
        except Exception:
            pass

    t1 = time.perf_counter()
    dt = t1 - t0
    rps = (args.rows / dt) if dt > 0 else 0.0
    print(
        f"stress_done rows={args.rows} seconds={dt:.3f} rows_per_s={rps:,.0f} "
        f"async_writer={bool(args.async_writer)} out={option_file}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
