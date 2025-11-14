#!/usr/bin/env python
from __future__ import annotations
import csv
import sys
import time
from datetime import datetime
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "grid"
POLL_SECS = 20


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
        return float(str(x))
    except Exception:
        return float("nan")


def has_large_scale_or_hybrid(rows: list[dict]) -> bool:
    if not rows:
        return False
    have_scale = False
    have_hybrid = False
    for r in rows:
        s = to_float(r.get("scale", 1.0))
        m = str(r.get("mode", ""))
        if s >= 1.3:
            have_scale = True
        if m.lower() == "hybrid":
            have_hybrid = True
    return have_scale or have_hybrid


def main():
    if len(sys.argv) < 4:
        print("Usage: watch_and_pick.py <INDEX> <TAG> <OFFSET> [<TARGET=0.8>] [<TOPN=3>]")
        raise SystemExit(2)
    index, tag, offset = sys.argv[1], sys.argv[2], sys.argv[3]
    target = float(sys.argv[4]) if len(sys.argv) > 4 else 0.8
    topn = int(sys.argv[5]) if len(sys.argv) > 5 else 3

    out_dir = RESULTS / index / tag / offset
    summ = out_dir / "summary.csv"
    log = out_dir / "watch_pick.log"
    done = out_dir / "PICKS_DONE.txt"

    out_dir.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] watch_and_pick started for {index}/{tag}/{offset}\n")  # local-ok

    # mtime reference
    prev_mtime = summ.stat().st_mtime if summ.exists() else 0

    while True:
        rows = read_summary(summ)
        if rows and has_large_scale_or_hybrid(rows):
            # run analyzer
            cmd = [sys.executable, str(ROOT / "scripts" / "ml" / "analyze_summary_pick.py"), index, tag, offset, str(target), str(topn)]
            try:
                subprocess.run(cmd, cwd=str(ROOT), check=True)
                with done.open("w", encoding="utf-8") as f:
                    f.write(datetime.now().isoformat(timespec='seconds'))  # local-ok
                with log.open("a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now().isoformat(timespec='seconds')}] picks computed and done written\n")  # local-ok
            except Exception as e:
                with log.open("a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now().isoformat(timespec='seconds')}] analyzer failed: {e}\n")  # local-ok
            break
        # wait for changes
        cur_mtime = summ.stat().st_mtime if summ.exists() else 0
        if cur_mtime != prev_mtime:
            with log.open("a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat(timespec='seconds')}] summary changed; rows={len(rows)}\n")  # local-ok
            prev_mtime = cur_mtime
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
