#!/usr/bin/env python3
"""
Auto-calibration daemon for ML path-forecast bands.

Monitors coverage via the advisor endpoint and triggers calibration updates
when the absolute coverage gap exceeds thresholds and enough samples exist.

- Polls /api/ml/path_advisor (read-only) per index/horizon
- On condition: POST /api/ml/path_calibrate with target and window
- Applies a per-key cooldown to avoid thrashing (default 15 minutes)
- Logs actions to logs/calibration.log

Examples (Windows PowerShell):
  ${command:python.interpreterPath} scripts/ml/auto_calibrate_daemon.py \
    --indices NIFTY,BANKNIFTY --horizon 60 --window-minutes 180 --interval 300

"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Tuple

DEFAULT_BASE = "http://127.0.0.1:9500"


def http_get_json(url: str, timeout: float = 5.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "g6-auto-cal/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {}


def http_post_json(url: str, params: Dict[str, object], timeout: float = 5.0) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items()})
    full = f"{url}?{qs}"
    req = urllib.request.Request(full, method="POST", headers={"User-Agent": "g6-auto-cal/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {}


def log_line(s: str) -> None:
    try:
        os.makedirs("logs", exist_ok=True)
        with open(os.path.join("logs", "calibration.log"), "a", encoding="utf-8") as f:
            f.write(s.rstrip() + "\n")
    except Exception:
        pass
    # Also echo to stdout for interactive runs
    print(s, flush=True)


def decide_and_calibrate(
    base_url: str,
    index: str,
    horizon: int,
    window_minutes: int,
    target: float,
    gap_warn: float,
    gap_crit: float,
    min_samples_warn: int,
    min_samples_crit: int,
) -> Tuple[bool, dict]:
    """Return (did_calibrate, last_payload)."""
    advisor_url = (
        f"{base_url}/api/ml/path_advisor?"
        + urllib.parse.urlencode(
            {
                "index": index,
                "horizon": horizon,
                "window_minutes": window_minutes,
                "gap_warn": gap_warn,
                "gap_crit": gap_crit,
                "min_samples_warn": min_samples_warn,
                "min_samples_crit": min_samples_crit,
            }
        )
    )
    adv = http_get_json(advisor_url)
    summary = adv.get("summary") or {}
    alerts = adv.get("alerts") or []
    cov = summary.get("coverage")
    gap = summary.get("gap")
    samples = int(summary.get("samples") or 0)

    # Decision logic:
    # - if samples below crit threshold: never calibrate
    # - if samples between crit and warn, only calibrate on crit gap
    # - if samples >= warn, calibrate on warn or crit gap
    gabs = abs(float(gap)) if isinstance(gap, (int, float)) else None
    should = False
    if samples <= int(min_samples_crit):
        should = False
    elif gabs is None:
        should = False
    elif int(min_samples_crit) < samples < int(min_samples_warn):
        should = bool(gabs >= float(gap_crit))
    else:
        should = bool(gabs >= float(gap_warn))

    if not should:
        return False, {"advisor": adv}

    # Perform calibration
    cal_url = f"{base_url}/api/ml/path_calibrate"
    payload = http_post_json(
        cal_url,
        {
            "index": index,
            "horizon": horizon,
            "window_minutes": window_minutes,
            "target": target,
        },
    )
    return True, {"advisor": adv, "calibration": payload}


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Auto-calibration daemon for path-forecast bands")
    p.add_argument("--base-url", default=DEFAULT_BASE)
    p.add_argument("--indices", default="NIFTY", help="Comma-separated indices e.g., NIFTY,BANKNIFTY")
    p.add_argument("--horizon", type=int, default=60)
    p.add_argument("--window-minutes", type=int, default=180)
    p.add_argument("--target", type=float, default=0.8)
    p.add_argument("--interval", type=int, default=300, help="Poll interval seconds")
    p.add_argument("--cooldown-sec", type=int, default=900, help="Cooldown after a calibration per key")
    p.add_argument("--gap-warn", type=float, default=0.05)
    p.add_argument("--gap-crit", type=float, default=0.10)
    p.add_argument("--min-samples-warn", type=int, default=30)
    p.add_argument("--min-samples-crit", type=int, default=10)
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    base = args.base_url.rstrip("/")
    indices = [s.strip().upper() for s in str(args.indices).split(",") if s.strip()]
    cooldown: Dict[Tuple[str, int], float] = {}

    log_line(
        f"[auto-cal] start base={base} indices={indices} H={args.horizon} W={args.window_minutes} target={args.target} interval={args.interval}s"
    )

    try:
        while True:
            now = time.time()
            for idx in indices:
                key = (idx, int(args.horizon))
                last = cooldown.get(key, 0.0)
                if now - last < float(args.cooldown_sec):
                    continue
                try:
                    did, payload = decide_and_calibrate(
                        base,
                        idx,
                        int(args.horizon),
                        int(args.window_minutes),
                        float(args.target),
                        float(args.gap_warn),
                        float(args.gap_crit),
                        int(args.min_samples_warn),
                        int(args.min_samples_crit),
                    )
                    summ = ((payload.get("advisor") or {}).get("summary") or {})
                    level = summ.get("level")
                    cov = summ.get("coverage")
                    samples = summ.get("samples")
                    gap = summ.get("gap")
                    if did:
                        cal = payload.get("calibration") or {}
                        new_scale = cal.get("band_scale")
                        actual = cal.get("actual")
                        log_line(
                            f"[auto-cal] CALIBRATED idx={idx} H={args.horizon} samples={samples} cov={cov} gap={gap} -> band_scale={new_scale} actual={actual}"
                        )
                        cooldown[key] = time.time()
                    else:
                        log_line(
                            f"[auto-cal] skip idx={idx} H={args.horizon} level={level} samples={samples} cov={cov} gap={gap}"
                        )
                except Exception as e:
                    log_line(f"[auto-cal] error idx={idx}: {e}")
            time.sleep(max(1, int(args.interval)))
    except KeyboardInterrupt:
        log_line("[auto-cal] stop (keyboard interrupt)")
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
