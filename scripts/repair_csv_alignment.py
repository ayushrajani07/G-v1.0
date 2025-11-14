#!/usr/bin/env python3
"""
Repair misaligned option CSV rows caused by mid-day header expansion.

Scenario:
- Existing file has legacy header (e.g., starts with 'timestamp,index,...')
- New rows appended with extra columns ['time','time_ms'] after 'timestamp' while header stayed legacy
- Result: values shift right and columns appear jumbled in Excel

Strategy:
- If the file header already includes 'time'/'time_ms', do nothing.
- Otherwise, detect rows where column 1 (expected 'index') actually looks like ISO8601 time (contains 'T')
  or the next field looks like epoch milliseconds (>= 1e11). For such rows, drop the two extra
  fields (time, time_ms) to realign to legacy header.
- Optionally compute legacy 'atm' if header expects it and it's missing, using: atm = strike - offset

Usage:
  python scripts/repair_csv_alignment.py --file data/g6_data/NIFTY/this_week/0/2025-11-04.csv [--dry-run]
  python scripts/repair_csv_alignment.py --glob "data/g6_data/*/*/*/2025-11-04.csv"

This script writes a backup alongside the original as <name>.backup and then rewrites the original in-place
unless --dry-run is passed.
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import re
from typing import List

ISO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def looks_like_iso(s: str) -> bool:
    return bool(ISO_PATTERN.match(s))


def looks_like_epoch_ms(s: str) -> bool:
    try:
        v = float(s)
        return v >= 1e11
    except Exception:
        return False


def repair_file(path: str, dry_run: bool = False) -> tuple[int, int, bool]:
    """Repair a single CSV file in-place.

    Returns: (total_rows, fixed_rows, changed)
    """
    if not os.path.isfile(path):
        return 0, 0, False

    with open(path, 'r', newline='', encoding='utf-8') as rf:
        rdr = csv.reader(rf)
        try:
            header = next(rdr)
        except StopIteration:
            return 0, 0, False
        rows = list(rdr)

    # If already updated schema, skip
    if 'time' in header and 'time_ms' in header:
        return len(rows), 0, False

    # Legacy header: ensure we can identify index/strike/offset positions
    # Expected header begins with: timestamp,index, ... possibly 'atm' exists later
    try:
        idx_index = header.index('index')
    except ValueError:
        idx_index = 1  # best-effort
    try:
        idx_offset = header.index('offset')
    except ValueError:
        idx_offset = None
    try:
        idx_strike = header.index('strike')
    except ValueError:
        idx_strike = None

    fixed = 0
    out_rows: List[List[str]] = []

    for r in rows:
        if not r:
            out_rows.append(r)
            continue
        # Detect misaligned pattern: r[1] looks like ISO OR r[2] looks like epoch ms
        needs_fix = False
        if len(r) >= 2 and looks_like_iso(r[1]):
            needs_fix = True
        elif len(r) >= 3 and looks_like_epoch_ms(r[2]):
            needs_fix = True
        if needs_fix:
            # Drop the two inserted fields (time, time_ms) appearing after timestamp
            # New aligned row = [timestamp] + r[3:]
            if len(r) >= 3:
                r = [r[0]] + r[3:]
                fixed += 1
        # Inject legacy 'atm' if header expects it and we can compute
        # Note: Only if the original header actually contains 'atm'
        if 'atm' in header and idx_offset is not None and idx_strike is not None:
            try:
                i_offset = int(r[idx_offset])
                f_strike = float(r[idx_strike])
                atm_val = f_strike - i_offset
                # Put back into the position of 'atm' column if exists
                try:
                    idx_atm = header.index('atm')
                    # If row is short, extend
                    if idx_atm >= len(r):
                        r += [''] * (idx_atm - len(r) + 1)
                    r[idx_atm] = str(atm_val)
                except ValueError:
                    pass
            except Exception:
                pass
        out_rows.append(r)

    if fixed and not dry_run:
        backup = path + '.backup'
        if not os.path.exists(backup):
            try:
                os.replace(path, backup)
            except Exception:
                # Fallback to copy if replace fails
                import shutil
                shutil.copy2(path, backup)
        with open(path, 'w', newline='', encoding='utf-8') as wf:
            w = csv.writer(wf)
            w.writerow(header)
            w.writerows(out_rows)

    return len(rows), fixed, fixed > 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ag = ap.add_mutually_exclusive_group(required=True)
    ag.add_argument('--file', help='Path to a single CSV file to repair')
    ag.add_argument('--glob', help='Glob pattern to select files (quoted)')
    ap.add_argument('--dry-run', action='store_true', help='Analyze only; do not write changes')
    args = ap.parse_args()

    files: List[str]
    if args.file:
        files = [args.file]
    else:
        files = sorted(glob.glob(args.glob))

    total = fixed = changed_files = 0
    for fp in files:
        rows, fx, changed = repair_file(fp, dry_run=args.dry_run)
        total += rows
        fixed += fx
        if changed:
            changed_files += 1
        print(f"REPAIR {os.path.basename(fp)}: rows={rows} fixed={fx} changed={changed}")

    print(f"SUMMARY: files={len(files)} changed_files={changed_files} total_rows={total} fixed_rows={fixed}")


if __name__ == '__main__':
    main()
