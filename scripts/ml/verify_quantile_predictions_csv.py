from __future__ import annotations

"""Quick verification utility for quantile predictions CSV.

Checks required columns (p10,p50,p90) exist in live predictions file for an index
and prints the last N rows plus basic stats.

Usage (PowerShell example):
  python scripts/ml/verify_quantile_predictions_csv.py --index NIFTY --tail 5
"""

import argparse
from pathlib import Path
import sys
import csv
from statistics import mean

from datetime import datetime, timezone

# Lazy import of project root mechanism; fallback to relative path search
try:
    from src.web.dashboard.core.paths import project_root  # type: ignore
except Exception:  # pragma: no cover
    project_root = lambda: Path(__file__).resolve().parents[2]

REQUIRED = ("p10", "p50", "p90")


def load_rows(fp: Path) -> list[dict[str, str]]:
    with fp.open("r", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        return list(rdr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, help="Index (e.g., NIFTY)")
    ap.add_argument("--tail", type=int, default=5, help="Show last N rows")
    args = ap.parse_args()

    base = project_root() / "data" / "ml" / "live_predictions"
    fp = base / f"{args.index.upper()}.csv"
    if not fp.exists():
        print(f"[error] file not found: {fp}")
        sys.exit(2)

    rows = load_rows(fp)
    if not rows:
        print(f"[warn] no rows in {fp}")
        sys.exit(1)

    missing = [c for c in REQUIRED if c not in rows[0]]
    if missing:
        print(f"[error] missing columns: {missing}")
        sys.exit(3)

    tail_rows = rows[-args.tail:]
    print(f"File: {fp} (total rows={len(rows)})")
    for r in tail_rows:
        print(r)

    # Basic stats over tail
    try:
        p50_vals = [float(r.get("p50", "nan")) for r in tail_rows]
        p10_vals = [float(r.get("p10", "nan")) for r in tail_rows]
        p90_vals = [float(r.get("p90", "nan")) for r in tail_rows]
        spread_mean = mean([(p90_vals[i] - p10_vals[i]) for i in range(len(p50_vals))]) if p50_vals else float("nan")
        print(f"Mean band spread (p90 - p10) over tail: {spread_mean:.4f}")
    except Exception as e:
        print(f"[warn] stats error: {e}")

    ts = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
    print(f"Verification timestamp: {ts}")


if __name__ == "__main__":
    main()
