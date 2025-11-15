#!/usr/bin/env python
from __future__ import annotations
import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import os
from src.error_handling import safe_write_text, safe_append_line

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "grid"
OUT_DIR = RESULTS / "COMBINED" / "this_week" / "0"
INDICES = ["NIFTY", "SENSEX", "BANKNIFTY"]
# Use per-index default tags (BANKNIFTY => this_month; others => this_week)
TAG_MAP = {
    "NIFTY": "this_week",
    "SENSEX": "this_week",
    "BANKNIFTY": "this_month",
}
OFFSET = "0"
POLL_SECS = 30
LOG = OUT_DIR / "watch.log"
DONE = OUT_DIR / "STATUS_DONE.txt"
LOCK = OUT_DIR / "watch.lock"


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


def has_valid_metrics(rows: list[dict]) -> bool:
    if not rows:
        return False
    samples_pos = 0
    metrics_rows = 0
    for r in rows:
        s = to_float(r.get("samples_avg")) if "samples_avg" in r else float("nan")
        cov = to_float(r.get("coverage_avg"))
        bw = to_float(r.get("band_width_avg"))
        mae = to_float(r.get("mae_avg"))
        if s == s and s > 0:
            samples_pos += 1
        if cov == cov and bw == bw and mae == mae:
            metrics_rows += 1
    # require at least one row with samples>0 and metrics non-NaN
    return samples_pos > 0 and metrics_rows > 0


def log(msg: str):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")  # local-ok
    if not LOG.exists():
        safe_write_text(LOG, "")
    safe_append_line(LOG, f"[{ts}] {msg}")


def main():
    # rotate log daily
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if LOG.exists():
        try:
            mtime = datetime.fromtimestamp(LOG.stat().st_mtime)
            today = datetime.now().date()  # local-ok
            if mtime.date() != today:
                ts = mtime.strftime("%Y%m%d-%H%M%S")
                LOG.rename(LOG.with_name(f"watch-{ts}.log"))
        except Exception:
            pass

    # simple PID guard
    try:
        if LOCK.exists():
            age = time.time() - LOCK.stat().st_mtime
            if age < 300:
                log("another watcher appears active; exiting")
                return
    except Exception:
        pass
    try:
        safe_write_text(LOCK, f"{os.getpid()}\n{datetime.now().isoformat(timespec='seconds')}\n")  # local-ok
    except Exception:
        pass

    log("watcher started (per-index tags: NIFTY/SENSEX=this_week, BANKNIFTY=this_month)")
    while True:
        all_ready = True
        for idx in INDICES:
            tag = TAG_MAP.get(idx, "this_week")
            summ = RESULTS / idx / tag / OFFSET / "summary.csv"
            if not summ.exists():
                log(f"{idx}: summary missing at {summ}")
                all_ready = False
                continue
            rows = read_summary(summ)
            if not has_valid_metrics(rows):
                log(f"{idx}: metrics not ready yet (rows={len(rows)})")
                all_ready = False
                continue
            log(f"{idx}: OK (rows={len(rows)})")
        if all_ready:
            log("all indices ready; running combiner")
            # Run combiner as a subprocess using same Python
            cmd = [sys.executable, str(ROOT / "scripts" / "ml" / "combine_grid_eval.py")]
            try:
                subprocess.run(cmd, cwd=str(ROOT), check=True)
                OUT_DIR.mkdir(parents=True, exist_ok=True)
                safe_write_text(DONE, datetime.now().isoformat(timespec="seconds"))  # local-ok
                log("combiner completed; status done written")
            except Exception as e:
                log(f"combiner failed: {e}")
            try:
                if LOCK.exists():
                    LOCK.unlink()
            except Exception:
                pass
            break
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
