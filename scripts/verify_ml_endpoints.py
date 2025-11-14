#!/usr/bin/env python3
"""
Quick verification of ML-related CSV endpoints on the Dashboard API.
- predictions, delta, diagnostics, correlations, model_matrix
Prints HTTP status and first few CSV lines for each endpoint.

Usage examples:
  python scripts/verify_ml_endpoints.py --base-url http://127.0.0.1:9500 \
    --index NIFTY --horizon 1 --model sk_hgb_regressor --window-minutes 600 --tail 5
"""
from __future__ import annotations
import argparse
import sys
import urllib.request
import urllib.error
from typing import List, Tuple


def fetch_lines(url: str, timeout: float = 8.0) -> Tuple[int, List[str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "verify-ml-endpoints/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, 'status', 200)
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            # Normalize newlines and split
            lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            # Trim trailing empty lines
            while lines and lines[-1] == "":
                lines.pop()
            return status, lines
    except urllib.error.HTTPError as e:
        return e.code, [f"HTTPError {e.code}: {e.reason}"]
    except urllib.error.URLError as e:
        return -1, [f"URLError: {e.reason}"]
    except Exception as e:
        return -1, [f"Error: {e}"]


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:9500", help="Dashboard base URL (default: %(default)s)")
    p.add_argument("--index", default="NIFTY", help="Index symbol (default: %(default)s)")
    p.add_argument("--horizon", type=int, default=1, help="Prediction horizon (default: %(default)s)")
    p.add_argument("--model", default="sk_hgb_regressor", help="Model name to filter (default: %(default)s)")
    p.add_argument("--window-minutes", type=int, default=600, help="Diagnostics/correlations window minutes (default: %(default)s)")
    p.add_argument("--tail", type=int, default=5, help="Tail rows for predictions/delta (default: %(default)s)")
    args = p.parse_args(argv)

    base = args.base_url.rstrip("/")

    endpoints = [
        ("predictions", f"{base}/api/ml/predictions?index={args.index}&horizon={args.horizon}&model={args.model}&tail={args.tail}"),
        ("delta", f"{base}/api/ml/delta?index={args.index}&horizon={args.horizon}&model={args.model}&tail={args.tail}"),
        ("diagnostics", f"{base}/api/ml/diagnostics?index={args.index}&horizon={args.horizon}&model={args.model}&window_minutes={args.window_minutes}"),
        ("correlations", f"{base}/api/ml/correlations?index={args.index}&window_minutes={args.window_minutes}&format=long"),
        ("model_matrix", f"{base}/api/ml/model_matrix?window_minutes={args.window_minutes}"),
    ]

    print(f"Verifying ML endpoints on {base} (index={args.index}, model={args.model})\n")
    failures = []
    for name, url in endpoints:
        status, lines = fetch_lines(url)
        ok = (status == 200 and lines)
        print(f"[{name}] GET {url}")
        print(f"  status: {status}{' (OK)' if ok else ' (FAIL)'}")
        preview = lines[:8]
        if preview:
            for ln in preview:
                print(f"    {ln}")
        else:
            print("    <no content>")
        print("")
        if not ok:
            failures.append(name)

    if failures:
        print(f"FAILED: {len(failures)} endpoint(s) failed -> {', '.join(failures)}")
        return 1
    print("All endpoints responded with content.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
