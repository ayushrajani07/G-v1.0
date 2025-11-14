#!/usr/bin/env python
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "grid"
INDICES = ["NIFTY", "SENSEX", "BANKNIFTY"]
TAG = "this_week"
OFFSET = "0"


def read_summary(path: Path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows


def to_float(x):
    try:
        return float(x)
    except Exception:
        return float("nan")


def main():
    any_missing = False
    for idx in INDICES:
        folder = RESULTS / idx / TAG / OFFSET
        summ = folder / "summary.csv"
        evalp = folder / "eval.csv"
        exist = summ.exists()
        mtime = datetime.fromtimestamp(summ.stat().st_mtime).isoformat(timespec="seconds") if exist else "-"
        rows = read_summary(summ)
        total = len(rows)
        samples_pos = 0
        metrics_ok = 0
        for r in rows:
            s = to_float(r.get("samples_avg")) if "samples_avg" in r else float("nan")
            if s == s and s > 0:
                samples_pos += 1
            cov = to_float(r.get("coverage_avg"))
            bw = to_float(r.get("band_width_avg"))
            mae = to_float(r.get("mae_avg"))
            if cov == cov and bw == bw and mae == mae:
                metrics_ok += 1
        print(f"{idx}: summary_exists={exist} rows={total} samples_avg>0_rows={samples_pos} metrics_rows={metrics_ok} mtime={mtime}")
        if not exist:
            any_missing = True
    if any_missing:
        print("STATUS: INCOMPLETE (one or more indices missing summary.csv)")
    else:
        print("STATUS: PRESENT (summaries exist for all indices)")


if __name__ == "__main__":
    main()
