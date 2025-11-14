from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from typing import List


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":", 1)
    return int(h), int(m)


def _iter_times_for_date(day: dt.date, start_hhmm: str, end_hhmm: str, step_sec: int) -> list[int]:
    sh, sm = _parse_hhmm(start_hhmm)
    eh, em = _parse_hhmm(end_hhmm)
    start = dt.datetime.combine(day, dt.time(hour=sh, minute=sm, second=0))
    end = dt.datetime.combine(day, dt.time(hour=eh, minute=em, second=0))
    # Return epoch ms in local (naive) time; server interprets based on CSV rows timestamps which are IST-aware.
    out: list[int] = []
    cur = start
    while cur <= end:
        out.append(int(cur.timestamp() * 1000))
        cur += dt.timedelta(seconds=max(1, step_sec))
    return out


def _get(url: str, timeout: float = 6.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return getattr(resp, "status", 200)
    except Exception:
        return 0


essential = ["index", "date", "start", "end", "step_sec", "horizon", "base_url"]

def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill multi-quantile bands for a given date by simulating past now_ms")
    p.add_argument("--index", default="NIFTY")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--start", default="09:30", help="Start HH:MM (local)")
    p.add_argument("--end", default="14:30", help="End HH:MM (local, inclusive)")
    p.add_argument("--step-sec", type=int, default=60, help="Step seconds between calls")
    p.add_argument("--horizon", type=int, default=60, help="Horizon minutes for JSON route")
    p.add_argument("--base-url", default="http://127.0.0.1:9500")
    p.add_argument("--expiry-tag", default="this_week")
    p.add_argument("--offset", default="0")
    p.add_argument("--window", type=int, default=60)
    p.add_argument("--k", type=int, default=15)
    p.add_argument("--mode", default="auto")
    p.add_argument("--bucket-ms", type=int, default=60_000)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    try:
        day = dt.date.fromisoformat(args.date)
    except Exception:
        print(json.dumps({"error": "invalid date", "date": args.date}), flush=True)
        return 2

    times = _iter_times_for_date(day, args.start, args.end, args.step_sec)
    base = args.base_url.rstrip('/')
    qbase = {
        "index": args.index.upper(),
        "expiry_tag": args.expiry_tag,
        "offset": args.offset,
        "window": str(int(args.window)),
        "k": str(int(args.k)),
        "mode": args.mode,
        "bucket_ms": str(int(args.bucket_ms)),
        "calibrate": "false",
        "no_cache": "true",
        "date_str": args.date,
    }

    print(f"[backfill] starting for index={qbase['index']} date={args.date} range={args.start}-{args.end} step={args.step_sec}s base={base}")
    ok = 0
    for i, nm in enumerate(times, 1):
        q = dict(qbase)
        q["horizon_minutes"] = str(int(args.horizon))
        q["now_override_ms"] = str(int(nm))
        url = f"{base}/api/ml/path_forecast_json?{urllib.parse.urlencode(q)}"
        status = _get(url, timeout=10.0)
        ok += 1 if status == 200 else 0
        if not args.quiet:
            print(json.dumps({"ts": int(time.time()), "i": i, "status": status, "now_ms": nm}, ensure_ascii=False), flush=True)
        # small delay to avoid hammering the server
        time.sleep(0.2)
    print(json.dumps({"completed": len(times), "ok": ok}), flush=True)
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
