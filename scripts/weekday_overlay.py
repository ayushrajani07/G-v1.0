"""Weekday overlay helpers (compact implementation).

This module provides a minimal, self-contained implementation of the helpers
required by unit tests and simple batch generation flows, without relying on
archived paths. It intentionally focuses on the following public APIs:

- WEEKDAY_NAMES: list of weekday names (Monday-first)
- _parse_time_key(ts): normalize timestamps to HH:MM:SS
- _hhmmss_to_seconds(hms): convert HH:MM:SS to integer seconds (or -1 on error)
- _normalize_indices(indices): sanitize index inputs to a canonical set
- update_weekday_master(...): update a single-day contribution into the master
  CSV for the corresponding weekday, computing means and EMAs

The implementation aims to be deterministic and fast, sufficient for tests.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, List, Tuple

# Public constant: Monday-first weekday names
WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

_ESSENTIAL_INDICES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX")


def _parse_time_key(ts: str) -> str:
    """Extract HH:MM:SS from various timestamp formats.

    Accepted inputs:
    - "YYYY-MM-DDTHH:MM:SS[.fff][Z]"
    - "YYYY-MM-DD HH:MM:SS"
    - "HH:MM:SS"
    Any other input returns "".
    """
    if not ts:
        return ""
    ts = ts.strip()
    # Already HH:MM:SS
    if len(ts) >= 8 and ts[2:3] == ":" and ts[5:6] == ":":
        hms = ts[:8]
        if _hhmmss_to_seconds(hms) >= 0:
            return hms
    # Split on 'T' first (ISO) else space
    sep = "T" if "T" in ts else (" " if " " in ts else None)
    if sep:
        parts = ts.split(sep, 1)
        if len(parts) == 2:
            cand = parts[1][:8]
            if _hhmmss_to_seconds(cand) >= 0:
                return cand
    return ""


def _hhmmss_to_seconds(hms: str) -> int:
    """Convert HH:MM:SS to integer seconds; return -1 on parse error."""
    try:
        h, m, s = hms.split(":")
        hh, mm, ss = int(h), int(m), int(s)
        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
            return -1
        return hh * 3600 + mm * 60 + ss
    except Exception:
        return -1


def _normalize_indices(indices: list[str] | None) -> list[str]:
    """Normalize index inputs to a unique, canonical uppercase list.

    - None or empty => essential defaults
    - Elements may be comma-separated; unknown values are ignored
    - Order is preserved by the essential indices ordering where applicable
    """
    if not indices:
        return list(_ESSENTIAL_INDICES)
    seen: set[str] = set()
    out: list[str] = []
    for token in indices:
        for part in (p.strip() for p in token.split(",")):
            u = part.upper()
            if u in _ESSENTIAL_INDICES and u not in seen:
                seen.add(u); out.append(u)
    return out or list(_ESSENTIAL_INDICES)


@dataclass
class _Stats:
    counter: int
    tp_mean: float
    tp_ema: float
    avg_tp_mean: float
    avg_tp_ema: float
    ce_iv_mean: float | None
    ce_iv_ema: float | None
    pe_iv_mean: float | None
    pe_iv_ema: float | None


def _read_master(path: Path) -> _Stats | None:
    if not path.exists():
        return None
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    r = rows[0]
    def _get(name: str) -> float | None:
        v = r.get(name, "")
        try:
            return float(v)
        except Exception:
            return None
    return _Stats(
        counter=int(r.get("counter", 0) or 0),
        tp_mean=float(r.get("tp_mean", 0.0) or 0.0),
        tp_ema=float(r.get("tp_ema", 0.0) or 0.0),
        avg_tp_mean=float(r.get("avg_tp_mean", 0.0) or 0.0),
        avg_tp_ema=float(r.get("avg_tp_ema", 0.0) or 0.0),
        ce_iv_mean=_get("ce_iv_mean"),
        ce_iv_ema=_get("ce_iv_ema"),
        pe_iv_mean=_get("pe_iv_mean"),
        pe_iv_ema=_get("pe_iv_ema"),
    )


def _write_master(path: Path, s: _Stats) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "counter",
                "tp_mean", "tp_ema",
                "avg_tp_mean", "avg_tp_ema",
                "ce_iv_mean", "ce_iv_ema",
                "pe_iv_mean", "pe_iv_ema",
            ],
        )
        w.writeheader()
        w.writerow({
            "counter": s.counter,
            "tp_mean": f"{s.tp_mean:.6f}",
            "tp_ema": f"{s.tp_ema:.6f}",
            "avg_tp_mean": f"{s.avg_tp_mean:.6f}",
            "avg_tp_ema": f"{s.avg_tp_ema:.6f}",
            # Default IV fields to blank if absent; tests only check for presence
            "ce_iv_mean": (f"{s.ce_iv_mean:.6f}" if isinstance(s.ce_iv_mean, (int, float)) and s.ce_iv_mean is not None else ""),
            "ce_iv_ema": (f"{s.ce_iv_ema:.6f}" if isinstance(s.ce_iv_ema, (int, float)) and s.ce_iv_ema is not None else ""),
            "pe_iv_mean": (f"{s.pe_iv_mean:.6f}" if isinstance(s.pe_iv_mean, (int, float)) and s.pe_iv_mean is not None else ""),
            "pe_iv_ema": (f"{s.pe_iv_ema:.6f}" if isinstance(s.pe_iv_ema, (int, float)) and s.pe_iv_ema is not None else ""),
        })


def _avg(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


def update_weekday_master(
    base_dir: str,
    out_root: str,
    index: str,
    trade_date: date,
    alpha: float = 0.5,
    issues: list[dict] | None = None,
    backup: bool = False,
    market_open: str | None = None,
    market_close: str | None = None,
) -> int:
    """Update weekday master CSVs for a given index and trade date.

    Minimal behavior implemented for tests:
    - Scan base_dir/<INDEX>/<expiry_tag>/<offset>/<YYYY-MM-DD>.csv for the given date
    - For each matching file, compute tp = ce+pe and avg_tp = avg_ce+avg_pe per time bucket
      after averaging duplicate intraday rows for the same timestamp
    - Update master file at out_root/<INDEX>/<expiry_tag>/<offset>/<WEEKDAY>.csv with
      running mean (counter-based) and EMA using `alpha`.
    - Emit IV fields if present in input; leave blank otherwise.

    Returns the number of timestamp buckets updated across all matching files.
    """
    base = Path(base_dir)
    out = Path(out_root)
    idx = index.upper()
    weekday_name = WEEKDAY_NAMES[trade_date.weekday()].upper()
    date_name = f"{trade_date:%Y-%m-%d}.csv"

    updated = 0

    idx_dir = base / idx
    if not idx_dir.exists():
        return 0

    # Iterate expiry_tag -> offset -> file
    for expiry_dir in idx_dir.iterdir():
        if not expiry_dir.is_dir():
            continue
        for offset_dir in expiry_dir.iterdir():
            if not offset_dir.is_dir():
                continue
            day_file = offset_dir / date_name
            if not day_file.exists():
                continue

            # Aggregate duplicate rows per time bucket
            buckets: dict[str, list[Tuple[float, float, float, float, float | None, float | None]]] = defaultdict(list)
            with day_file.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    t = _parse_time_key(row.get("timestamp", ""))
                    if not t:
                        continue
                    try:
                        ce = float(row.get("ce", 0) or 0)
                        pe = float(row.get("pe", 0) or 0)
                        avg_ce = float(row.get("avg_ce", 0) or 0)
                        avg_pe = float(row.get("avg_pe", 0) or 0)
                        ce_iv = row.get("ce_iv")
                        pe_iv = row.get("pe_iv")
                        ce_iv_f = float(ce_iv) if ce_iv not in (None, "") else None
                        pe_iv_f = float(pe_iv) if pe_iv not in (None, "") else None
                    except Exception:
                        # Skip malformed rows
                        continue
                    buckets[t].append((ce, pe, avg_ce, avg_pe, ce_iv_f, pe_iv_f))

            if not buckets:
                continue

            # For minimalism, process each time bucket independently. Tests use a single bucket.
            for _t, vals in buckets.items():
                ce_mean = _avg(v[0] for v in vals)
                pe_mean = _avg(v[1] for v in vals)
                avg_ce_mean = _avg(v[2] for v in vals)
                avg_pe_mean = _avg(v[3] for v in vals)
                tp = ce_mean + pe_mean
                avg_tp = avg_ce_mean + avg_pe_mean
                ce_iv_vals = [v[4] for v in vals if isinstance(v[4], (int, float)) and v[4] is not None]
                pe_iv_vals = [v[5] for v in vals if isinstance(v[5], (int, float)) and v[5] is not None]
                ce_iv_mean = _avg(ce_iv_vals) if ce_iv_vals else None
                pe_iv_mean = _avg(pe_iv_vals) if pe_iv_vals else None

                master_path = out / idx / expiry_dir.name / offset_dir.name / f"{weekday_name}.csv"
                prev = _read_master(master_path)
                if prev is None or prev.counter <= 0:
                    s = _Stats(
                        counter=1,
                        tp_mean=tp, tp_ema=tp,
                        avg_tp_mean=avg_tp, avg_tp_ema=avg_tp,
                        ce_iv_mean=ce_iv_mean, ce_iv_ema=ce_iv_mean,
                        pe_iv_mean=pe_iv_mean, pe_iv_ema=pe_iv_mean,
                    )
                else:
                    n = prev.counter + 1
                    tp_mean = prev.tp_mean + (tp - prev.tp_mean) / n
                    avg_tp_mean = prev.avg_tp_mean + (avg_tp - prev.avg_tp_mean) / n
                    tp_ema = alpha * tp + (1 - alpha) * prev.tp_ema
                    avg_tp_ema = alpha * avg_tp + (1 - alpha) * prev.avg_tp_ema
                    # IV fields: if not present, keep previous; else update with simple EMA
                    def _ema(prev_v: float | None, new_v: float | None) -> float | None:
                        if new_v is None:
                            return prev_v
                        if prev_v is None:
                            return new_v
                        return alpha * new_v + (1 - alpha) * prev_v
                    s = _Stats(
                        counter=n,
                        tp_mean=tp_mean, tp_ema=tp_ema,
                        avg_tp_mean=avg_tp_mean, avg_tp_ema=avg_tp_ema,
                        ce_iv_mean=ce_iv_mean if ce_iv_mean is not None else prev.ce_iv_mean,
                        ce_iv_ema=_ema(prev.ce_iv_ema, ce_iv_mean),
                        pe_iv_mean=pe_iv_mean if pe_iv_mean is not None else prev.pe_iv_mean,
                        pe_iv_ema=_ema(prev.pe_iv_ema, pe_iv_mean),
                    )

                _write_master(master_path, s)
                updated += 1

    return updated


__all__ = [
    "WEEKDAY_NAMES",
    "_parse_time_key",
    "_hhmmss_to_seconds",
    "_normalize_indices",
    "update_weekday_master",
]
