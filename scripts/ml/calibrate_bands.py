from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from typing import List, Dict, Any


# Standardized sleep helper using centralized backoff if available
try:
    from src.utils.backoff import sleep_ms as _sleep_ms  # type: ignore
except Exception:  # pragma: no cover
    _sleep_ms = None  # type: ignore

def _sleep_s(_sec: float) -> None:
    try:
        ms = int(float(_sec) * 1000)
        if _sleep_ms:
            _sleep_ms(ms)
        else:
            time.sleep(float(_sec))
    except Exception:
        time.sleep(float(_sec))


def _call(url: str, timeout: float = 5.0) -> tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url=url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
            data = resp.read().decode("utf-8", errors="replace")
            try:
                obj = json.loads(data) if data else {}
            except Exception:
                obj = {"raw": data}
            return int(code), obj if isinstance(obj, dict) else {"data": obj}
    except Exception as e:
        return 0, {"error": str(e)}


essential_keys = ("band_scale", "prev", "target", "actual", "samples")


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Calibrate path-forecast uncertainty bands against target coverage")
    p.add_argument("--indices", default="NIFTY", help="Comma-separated indices (e.g., NIFTY,BANKNIFTY)")
    p.add_argument("--horizons", default="30,60", help="Comma-separated horizons in minutes (e.g., 30,60)")
    p.add_argument("--window-minutes", type=int, default=180, help="Lookback window in minutes")
    p.add_argument("--target", type=float, default=0.8, help="Desired coverage for [q10,q90]")
    p.add_argument("--base-url", default="http://127.0.0.1:9500", help="Dashboard API base URL")
    p.add_argument("--expiry-tag", default="this_week", help="Expiry tag for live_csv lookup")
    p.add_argument("--offset", default="0", help="Offset for live_csv lookup (e.g., 0 or +0)")
    p.add_argument("--date-str", default="", help="Optional YYYY-MM-DD (off-hours testing)")
    p.add_argument("--retries", type=int, default=1, help="Retries per call on failure")
    p.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between calls")
    p.add_argument("--quiet", action="store_true", help="Reduce console output")

    args = p.parse_args(argv)
    indices = [s.strip().upper() for s in str(args.indices).split(',') if s.strip()]
    horizons = []
    for tok in str(args.horizons).split(','):
        tok = tok.strip()
        if not tok:
            continue
        try:
            horizons.append(int(tok))
        except Exception:
            pass
    horizons = [h for h in horizons if h > 0]
    if not indices or not horizons:
        print("No indices or horizons provided", file=sys.stderr)
        return 2

    base = args.base_url.rstrip('/')
    summary: List[Dict[str, Any]] = []

    for idx in indices:
        for h in horizons:
            q = {
                "index": idx,
                "expiry_tag": args.expiry_tag,
                "offset": args.offset,
                "window_minutes": str(int(args.window_minutes)),
                "horizon": str(int(h)),
                "target": str(float(args.target)),
            }
            if args.date_str:
                q["date_str"] = str(args.date_str)
            url = f"{base}/api/ml/path_calibrate?{urllib.parse.urlencode(q)}"
            attempt = 0
            code = 0
            payload: Dict[str, Any] = {}
            while attempt <= max(0, int(args.retries)):
                code, payload = _call(url, timeout=6.0)
                if code == 200:
                    break
                attempt += 1
                _sleep_s(0.5)
            row = {
                "index": idx,
                "horizon": h,
                "status": code,
            }
            row.update({k: payload.get(k) for k in essential_keys if isinstance(payload, dict)})
            err = payload.get("error") if isinstance(payload, dict) else None
            if err:
                row["error"] = err
            summary.append(row)
            if not args.quiet:
                print(json.dumps({"url": url, "result": row}, ensure_ascii=False))
            if args.sleep > 0:
                _sleep_s(float(args.sleep))

    # Print compact CSV-ish summary
    if not args.quiet:
        print("index,horizon,status,band_scale,prev,target,actual,samples,error")
        for r in summary:
            print(
                f"{r.get('index')},{r.get('horizon')},{r.get('status')},"
                f"{r.get('band_scale','')},{r.get('prev','')},{r.get('target','')},"
                f"{r.get('actual','')},{r.get('samples','')},{r.get('error','')}"
            )

    # Exit non-zero only if all failed for actionable reasons.
    # Treat common early-day/off-hours conditions as non-fatal:
    #  - 404 with "no bands archive for date" (archiver hasn’t populated yet)
    #  - 503 with "no live rows" or related
    ok = False
    for r in summary:
        st = int(r.get("status", 0))
        if st == 200:
            ok = True
            break
        err = (r.get("error") or "").lower()
        if st == 404 and ("no bands archive" in err or "live_csv not found" in err):
            ok = True
        if st == 503 and ("no live rows" in err or "no realized map" in err):
            ok = True
    # If at least one was OK or non-fatal, exit 0 so CI/tasks don’t flap early in the day
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
