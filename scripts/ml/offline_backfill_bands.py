from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Optional, Sequence

# Ensure project root is importable
import sys
from pathlib import Path as _Path
# Make project root importable regardless of where this script is run from
_ROOT = _Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from scripts._bootstrap import PROJECT_ROOT  # noqa: F401

from src.path_forecast.composite import CompositePathForecaster, CompositeConfig
from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig
from src.path_forecast.archive import ArchiveConfig, append_quantile_bands_snapshot

# Reuse helpers from the API route for locating and loading CSVs
from src.web.dashboard.routes.path_forecast import _find_live_csv, _load_csv_rows_full


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":", 1)
    return int(h), int(m)


def _iter_times_for_date(day: dt.date, start_hhmm: str, end_hhmm: str, step_sec: int) -> list[int]:
    sh, sm = _parse_hhmm(start_hhmm)
    eh, em = _parse_hhmm(end_hhmm)
    start = dt.datetime.combine(day, dt.time(hour=sh, minute=sm, second=0))
    end = dt.datetime.combine(day, dt.time(hour=eh, minute=em, second=0))
    out: list[int] = []
    cur = start
    step_sec = max(1, int(step_sec))
    while cur <= end:
        out.append(int(cur.timestamp() * 1000))
        cur += dt.timedelta(seconds=step_sec)
    return out


def _recent_tp_up_to(rows: list[dict], now_ms: int, lookback: int = 120) -> list[list[float]]:
    """Return last N tp values not after now_ms as [[tp], ...]."""
    buf: list[float] = []
    for r in rows:
        try:
            tms = int(r.get("ts") or r.get("time") or 0)
            tpv = r.get("tp")
        except Exception:
            continue
        if not tms or tms > now_ms:
            continue
        if isinstance(tpv, (int, float)):
            buf.append(float(tpv))
    if not buf:
        return []
    return [[v] for v in buf[-lookback:]]


def run_once(index: str, the_date: dt.date, now_ms: int, expiry_tag: str, offset: str, window: int, k: int,
             mode: str, horizon_minutes: int, bucket_ms: int) -> bool:
    base = PROJECT_ROOT / "data" / "g6_data"
    p_live = _find_live_csv(base, index, expiry_tag, offset, the_date)
    if not p_live or not p_live.exists():
        return False
    rows = _load_csv_rows_full(p_live)
    if not rows:
        return False
    # Find last tp at or before now_ms; align generation time to the matched row timestamp
    last_tp: Optional[float] = None
    ref_now_ms: Optional[int] = None
    for r in reversed(rows):
        try:
            tms = int(r.get("ts") or r.get("time") or 0)
        except Exception:
            continue
        if not tms or tms > now_ms:
            continue
        tpv = r.get("tp")
        if isinstance(tpv, (int, float)):
            last_tp = float(tpv)
            ref_now_ms = int(tms)
            break
    if last_tp is None or ref_now_ms is None:
        return False
    # Use the aligned ref time for recent window and as generation time
    now_ms = int(ref_now_ms)
    recent_tp = _recent_tp_up_to(rows, now_ms, lookback=120)
    qs = [0.1, 0.5, 0.9]

    times: Sequence[int] = []
    qmap: dict[float, Sequence[float]] = {}

    try:
        if mode.lower() in ("auto", "hybrid"):
            ccfg = CompositeConfig(root=base, expiry_tag=expiry_tag, offset=offset, window=int(window), k=int(k))
            comp = CompositePathForecaster(ccfg)
            times, qmap = comp.forecast_path(
                recent_tp,
                context={"index": index, "now_ms": now_ms, "live_rows": rows},
                quantiles=qs,
                horizon_minutes=int(horizon_minutes),
                bucket_ms=int(bucket_ms),
            )
        else:
            rcfg = RetrievalConfig(root=base, expiry_tag=expiry_tag, offset=offset, window=int(window), k=int(k))
            retr = RetrievalPathForecaster(rcfg)
            times, qmap = retr.forecast_path(
                recent_tp,
                context={"index": index, "now_ms": now_ms, "live_rows": rows},
                quantiles=qs,
                horizon_minutes=int(horizon_minutes),
                bucket_ms=int(bucket_ms),
            )
    except Exception:
        # Fallback: produce empty
        return False

    if not times or not qmap:
        return False

    # Write bands archive (uncalibrated values)
    arch_dir = PROJECT_ROOT / "data" / "ml" / "path_forecasts"
    acfg = ArchiveConfig(base_dir=arch_dir)
    try:
        append_quantile_bands_snapshot(acfg, index=index, gen_ms=now_ms, times=times, qmap=qmap)
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline backfill multi-quantile bands for a date without calling the API")
    ap.add_argument("--index", default="NIFTY")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--start", default="09:30")
    ap.add_argument("--end", default="14:30")
    ap.add_argument("--step-sec", type=int, default=60)
    ap.add_argument("--expiry-tag", default="this_week")
    ap.add_argument("--offset", default="0")
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--k", type=int, default=15)
    ap.add_argument("--mode", default="auto", choices=["auto","hybrid","retrieval","stub"])  # stub treated as retrieval here
    ap.add_argument("--horizon", type=int, default=60)
    ap.add_argument("--bucket-ms", type=int, default=60_000)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    try:
        day = dt.date.fromisoformat(args.date)
    except Exception:
        print(json.dumps({"error": "invalid date", "date": args.date}), flush=True)
        return 2

    times = _iter_times_for_date(day, args.start, args.end, int(args.step_sec))
    ok = 0
    for i, nm in enumerate(times, 1):
        ok += 1 if run_once(args.index.upper(), day, nm, args.expiry_tag, args.offset, int(args.window), int(args.k), args.mode, int(args.horizon), int(args.bucket_ms)) else 0
        if not args.quiet:
            print(json.dumps({"i": i, "now_ms": nm, "ok": ok}, ensure_ascii=False), flush=True)
    print(json.dumps({"completed": len(times), "ok": ok}), flush=True)
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
