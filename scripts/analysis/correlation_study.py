#!/usr/bin/env python3
"""
Correlation study harness for G6 live CSVs.

- Loads today's live CSV for a given index/expiry/offset
- Computes correlations for predefined column sets or a custom column list
- Writes both long and wide CSVs under data/analysis/<INDEX>/correlations/

Usage (PowerShell):
  # default (NIFTY, this_week, 0, last 120 min)
  py -3 scripts/analysis/correlation_study.py

  # BANKNIFTY, custom window and columns
  py -3 scripts/analysis/correlation_study.py --index BANKNIFTY --window-minutes 240 --cols "index_price,tp,ce_vol,pe_vol"
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import List, Optional

# Ensure project root on sys.path (works even when executed from nested folder)
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
try:
    # scripts/analysis -> scripts -> project_root
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    # Optional convenience import (no hard failure if missing)
    try:
        from _bootstrap import PROJECT_ROOT as _PR  # noqa: F401
    except Exception:
        pass
except Exception:
    pass

from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full  # type: ignore


def compute_correlations(rows: list[dict], cols: list[str], window_minutes: int, bucket_ms: int = 60_000):
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    cutoff_ms = now_ms - window_minutes * 60_000
    # Bucketize and collect latest values per bucket
    buckets: dict[int, dict[str, float]] = {}
    day_open_tp: Optional[float] = None
    last_tp: Optional[float] = None
    for r in rows:
        try:
            ems = int(r.get("ts") or r.get("time") or 0)
        except Exception:
            continue
        if not ems or ems < cutoff_ms:
            continue
        b = (ems // bucket_ms) * bucket_ms
        rec = buckets.get(b)
        if rec is None:
            rec = {}
            buckets[b] = rec
        for c in cols:
            v = r.get(c)
            if isinstance(v, (int, float)):
                rec[c] = float(v)
        # derived fields
        tp = r.get("tp")
        if isinstance(tp, (int, float)):
            tp_f = float(tp)
            if last_tp is not None:
                rec.setdefault("tp_net_change", tp_f - last_tp)
            last_tp = tp_f
            if day_open_tp is None:
                day_open_tp = tp_f
            rec.setdefault("tp_day_change", tp_f - (day_open_tp or tp_f))

    keys = sorted(buckets.keys())
    present_cols = [c for c in cols if any(c in buckets[k] for k in keys)]
    series: dict[str, List[float]] = {c: [] for c in present_cols}
    for k in keys:
        rec = buckets[k]
        for c in present_cols:
            v = rec.get(c)
            series[c].append(float(v) if isinstance(v, (int, float)) else float("nan"))

    def _pair_corr(xs: List[float], ys: List[float]):
        import math
        pairs = [(x, y) for x, y in zip(xs, ys) if (x == x) and (y == y)]
        n = len(pairs)
        if n < 3:
            return float("nan"), n
        mx = sum(x for x, _ in pairs) / n
        my = sum(y for _, y in pairs) / n
        cov = sum((x - mx) * (y - my) for x, y in pairs) / (n - 1)
        vx = sum((x - mx) ** 2 for x, _ in pairs) / (n - 1)
        vy = sum((y - my) ** 2 for _, y in pairs) / (n - 1)
        if vx <= 0 or vy <= 0:
            return float("nan"), n
        return cov / math.sqrt(vx * vy), n

    # Build long and wide outputs
    long_rows = ["col_i,col_j,correlation,count,window_minutes"]
    cols_eff = present_cols
    wide_rows = [",".join(["col", *cols_eff])]
    for i, ci in enumerate(cols_eff):
        # wide row
        wr = [ci]
        for j, cj in enumerate(cols_eff):
            if i == j:
                wr.append("1.0")
                long_rows.append(f"{ci},{cj},1.0,{len(series[ci])},{window_minutes}")
            else:
                r, n = _pair_corr(series[ci], series[cj])
                wr.append(f"{r:.4f}" if (r == r) else "")
                if j >= i:  # upper triangle + diagonal
                    long_rows.append(f"{ci},{cj},{(f'{r:.4f}' if (r == r) else '')},{n},{window_minutes}")
        wide_rows.append(",".join(wr))

    return "\n".join(long_rows), "\n".join(wide_rows)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Correlation study for G6 live CSVs")
    ap.add_argument("--index", default="NIFTY")
    ap.add_argument("--expiry-tag", default="this_week")
    ap.add_argument("--offset", default="0")
    ap.add_argument("--window-minutes", type=int, default=120)
    ap.add_argument("--bucket-ms", type=int, default=60_000)
    ap.add_argument("--set", default="set1", choices=["set1", "set2", "all"]) 
    ap.add_argument("--cols", help="Comma-separated explicit column list")
    ap.add_argument("--outdir", help="Output directory root", default="data/analysis")
    args = ap.parse_args(argv)

    # Resolve columns
    set1 = ["index_price", "ce_vol", "pe_vol", "ce_oi", "pe_oi", "ce_iv", "pe_iv", "tp"]
    set2 = set1 + [
        "ce_delta", "pe_delta", "ce_theta", "pe_theta", "ce_vega", "pe_vega", "ce_gamma", "pe_gamma", "ce_rho", "pe_rho",
        "tp_net_change", "tp_day_change",
    ]
    if args.cols:
        cols = [c.strip() for c in args.cols.split(",") if c.strip()]
    elif args.set == "set2":
        cols = set2
    elif args.set == "all":
        # fallback union; will be filtered by presence later
        cols = sorted(set(set2))
    else:
        cols = set1

    # Load
    from datetime import date
    root = Path("data/g6_data").resolve()
    p = find_live_csv(root, args.index.upper(), args.expiry_tag, args.offset, date.today())
    if not p or not p.exists():
        print(f"error: live_csv not found for {args.index} {args.expiry_tag} {args.offset}")
        return 2
    rows = load_csv_rows_full(p)

    long_csv, wide_csv = compute_correlations(rows, cols, args.window_minutes, args.bucket_ms)

    # Write to outdir
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_base = Path(args.outdir) / args.index.upper() / "correlations"
    out_base.mkdir(parents=True, exist_ok=True)
    long_path = out_base / f"corr_{args.set}_{ts}_long.csv"
    wide_path = out_base / f"corr_{args.set}_{ts}_wide.csv"
    long_path.write_text(long_csv, encoding="utf-8")
    wide_path.write_text(wide_csv, encoding="utf-8")
    print(f"wrote: {long_path}")
    print(f"wrote: {wide_path}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
