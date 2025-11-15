from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Sequence
import csv

# Simple compatibility shim for legacy tests expecting storage.csvio.api
# Provides append_one / append_many with optional 'atomic' backend semantics.
# Atomic semantics here: ensure header exists, align incoming row to existing header order,
# compute 'atm' when existing header has 'atm' but incoming header omits it (using strike-offset),
# and preserve existing header ordering.


def _detect_backend(passed: str | None) -> str:
    if passed:
        return passed
    return os.environ.get("G6_CSVIO_BACKEND", "facade").lower()


def _read_header(fp: Path) -> List[str] | None:
    if not fp.exists():
        return None
    try:
        with fp.open('r', newline='') as f:
            rdr = csv.reader(f)
            first = next(rdr, None)
            if isinstance(first, list):
                return first
    except Exception:
        return None
    return None


def _ensure_newline_if_missing(fp: Path) -> None:
    try:
        if not fp.exists():
            return
        with fp.open('rb') as f:
            data = f.read()
        if not data:
            return
        if data[-1:] in (b'\n', b'\r'):
            return
        # Append newline
        with fp.open('ab') as f:
            f.write(b'\n')
    except Exception:
        pass


def _compute_atm(row_map: dict[str, str]) -> str:
    try:
        strike = row_map.get('strike')
        offset = row_map.get('offset')
        if strike is None or offset is None:
            return ''
        s = float(str(strike))
        o = float(str(offset))
        return str(s - o)
    except Exception:
        return ''


def _align_row(existing_header: Sequence[str], provided_header: Sequence[str], row: Sequence[str]) -> List[str]:
    # Build mapping from provided header to values
    row_map = {h: row[i] for i, h in enumerate(provided_header) if i < len(row)}
    result: List[str] = []
    have_atm = 'atm' in existing_header
    provided_has_atm = 'atm' in provided_header
    atm_val = ''
    if have_atm and not provided_has_atm:
        atm_val = _compute_atm(row_map)
    for col in existing_header:
        if col == 'atm' and not provided_has_atm:
            result.append(atm_val)
            continue
        result.append(row_map.get(col, ''))
    return result


def append_one(path: str, row: Sequence[str], header: Sequence[str] | None = None, backend: str | None = None) -> None:
    fp = Path(path)
    be = _detect_backend(backend)
    exists = fp.exists()
    existing_header = _read_header(fp)

    if not exists:
        fp.parent.mkdir(parents=True, exist_ok=True)
        # When file is new: write header (if provided) then row (aligned to that header)
        hdr = list(header or [])
        with fp.open('w', newline='') as f:
            w = csv.writer(f)
            if hdr:
                w.writerow(hdr)
            w.writerow(row)
        return

    # Existing file
    if be == 'atomic':
        _ensure_newline_if_missing(fp)
    if existing_header and header and existing_header != list(header):
        # Need alignment
        out_row = _align_row(existing_header, header, row)
    elif existing_header and not header:
        # Provided no header, assume order matches file header length
        if len(row) == len(existing_header):
            out_row = list(row)
        else:
            # Pad/truncate to header length
            out_row = list(row)[:len(existing_header)] + [''] * max(0, len(existing_header) - len(row))
    else:
        out_row = list(row)
    with fp.open('a', newline='') as f:
        w = csv.writer(f)
        w.writerow(out_row)


def append_many(path: str, rows: Iterable[Sequence[str]], header: Sequence[str] | None = None, backend: str | None = None) -> None:
    fp = Path(path)
    be = _detect_backend(backend)
    exists = fp.exists()
    if not exists:
        fp.parent.mkdir(parents=True, exist_ok=True)
        hdr = list(header or [])
        with fp.open('w', newline='') as f:
            w = csv.writer(f)
            if hdr:
                w.writerow(hdr)
            for r in rows:
                w.writerow(list(r))
        return
    existing_header = _read_header(fp)
    if be == 'atomic':
        _ensure_newline_if_missing(fp)
    with fp.open('a', newline='') as f:
        w = csv.writer(f)
        for r in rows:
            if existing_header and header and existing_header != list(header):
                out_row = _align_row(existing_header, header, r)
            else:
                out_row = list(r)
            w.writerow(out_row)

__all__ = ["append_one", "append_many"]
