from __future__ import annotations

import csv
from collections import OrderedDict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from .config import CSV_CACHE_MAX

# In-process CSV cache: path -> (mtime_ns, rows_full)
_CSV_CACHE: OrderedDict[Path, tuple[int, list[dict[str, Any]]]] = OrderedDict()


def parse_time_any(s: str) -> str:
    """Best-effort parse of CSV timestamp to ISO 8601 string.
    CSV timestamps are in IST (Asia/Kolkata timezone).
    Returns original string if parsing fails.
    """
    from datetime import timezone, timedelta
    
    s = (s or '').strip()
    if not s:
        return s
    iso_try = s.replace(' ', 'T') if ('T' not in s and ' ' in s) else s
    dt = None
    try:
        dt = datetime.fromisoformat(iso_try)
    except Exception:
        pass
    if dt is None:
        # Try multiple timestamp formats found in CSV files
        for fmt in (
            '%d-%m-%Y %H:%M:%S',      # 16-09-2025 09:16:00
            '%Y-%m-%d %H:%M:%S',      # 2025-09-16 09:16:00
            '%d/%m/%Y %H:%M:%S',      # 16/09/2025 09:16:00
            '%m/%d/%Y %H:%M:%S',      # 09/16/2025 09:16:00
            '%d-%m-%Y %H:%M',         # 16-09-2025 09:16 (no seconds)
            '%Y-%m-%d %H:%M',         # 2025-09-16 09:16
            '%d/%m/%Y %H:%M',         # 16/09/2025 09:16
            '%m/%d/%Y %H:%M',         # 09/16/2025 09:16
            '%d/%m/%Y %I:%M',         # 1/10/2025 9:26 (single digit, 12-hour)
            '%m/%d/%Y %I:%M',         # 1/10/2025 9:26 (single digit, 12-hour)
        ):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except Exception:
                continue
    if dt is None:
        return s
    
    # CSV timestamps are in IST (UTC+5:30), not UTC
    # Make the naive datetime timezone-aware as IST
    ist = timezone(timedelta(hours=5, minutes=30))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ist)
    
    # Return ISO format with timezone
    return dt.isoformat()


def parse_time_epoch_ms(s: str) -> int | None:
    """Parse timestamp to epoch milliseconds.
    CSV timestamps are in IST (Asia/Kolkata timezone).
    """
    try:
        raw = (s or '').strip()
        if not raw:
            return None
        iso = raw.replace(' ', 'T') if ('T' not in raw and ' ' in raw) else raw
        dt = None
        try:
            dt = datetime.fromisoformat(iso)
        except Exception:
            pass
        if dt is None:
            # Try multiple timestamp formats found in CSV files
            for fmt in (
                '%d-%m-%Y %H:%M:%S',      # 16-09-2025 09:16:00
                '%Y-%m-%d %H:%M:%S',      # 2025-09-16 09:16:00
                '%d/%m/%Y %H:%M:%S',      # 16/09/2025 09:16:00
                '%m/%d/%Y %H:%M:%S',      # 09/16/2025 09:16:00
                '%d-%m-%Y %H:%M',         # 16-09-2025 09:16 (no seconds)
                '%Y-%m-%d %H:%M',         # 2025-09-16 09:16
                '%d/%m/%Y %H:%M',         # 16/09/2025 09:16
                '%m/%d/%Y %H:%M',         # 09/16/2025 09:16
                '%d/%m/%Y %I:%M',         # 1/10/2025 9:26 (single digit, 12-hour)
                '%m/%d/%Y %I:%M',         # 1/10/2025 9:26 (single digit, 12-hour)
            ):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except Exception:
                    continue
        if dt is None:
            return None
        if dt.tzinfo is None:
            # CSV timestamps are in IST (UTC+5:30), not UTC
            ist = timezone(timedelta(hours=5, minutes=30))
            dt = dt.replace(tzinfo=ist)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def norm_offset_folder(offset: str) -> str:
    v = (offset or '').strip()
    if not v:
        return v
    up = v.upper()
    if up == 'ATM':
        return '0'
    if up.startswith('+') or up.startswith('-'):
        return v
    if up.isdigit():
        return f"+{v}"
    return v


def find_live_csv(root: Path, index: str, expiry_tag: str, offset: str, day: date) -> Path | None:
    idx = (index or '').upper().strip()
    off = norm_offset_folder(offset)
    ymd = day.strftime('%Y-%m-%d')
    p = root / idx / expiry_tag / off / f"{ymd}.csv"
    if p.exists():
        return p
    if off.startswith('+') and off[1:].isdigit():
        raw = off[1:]
        q = root / idx / expiry_tag / raw / f"{ymd}.csv"
        if q.exists():
            return q
    q2 = root / idx / expiry_tag.lower() / off / f"{ymd}.csv"
    if q2.exists():
        return q2
    return None


def find_overlay_csv(root: Path, weekday: str, index: str, expiry_tag: str, offset: str) -> Path | None:
    candidates: list[Path] = []
    candidates.append(root / weekday / index / expiry_tag / f"{offset}.csv")
    if offset.upper() == 'ATM':
        candidates.append(root / weekday / index / expiry_tag / "0.csv")
    candidates.append(root / index / expiry_tag / offset / f"{weekday}.csv")
    if offset.upper() == 'ATM':
        candidates.append(root / index / expiry_tag / '0' / f"{weekday}.csv")
    # Try with + prefix for positive numeric offsets
    if offset and offset[0].isdigit():
        candidates.append(root / index / expiry_tag / f"+{offset}" / f"{weekday}.csv")
    # Try with - prefix for negative offsets (in case passed without -)
    if offset and offset.startswith('-') and offset[1:].isdigit():
        # Already has -, try as-is first (already added above)
        pass
    day_dir = root / weekday
    candidates.append(day_dir / f"{index}_{expiry_tag}_{offset}.csv")
    if offset.upper() == 'ATM':
        candidates.append(day_dir / f"{index}_{expiry_tag}_0.csv")
    if offset and offset[0].isdigit():
        candidates.append(day_dir / f"{index}_{expiry_tag}_+{offset}.csv")
    for p in candidates:
        if p.exists():
            return p
    return None


def load_csv_rows_full(path: Path) -> list[dict[str, Any]]:
    try:
        st = path.stat()
        mtime_ns = int(getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))
    except Exception:
        mtime_ns = 0
    cached = _CSV_CACHE.get(path)
    if cached and cached[0] == mtime_ns:
        try:
            _CSV_CACHE.move_to_end(path)
        except Exception:
            pass
        return cached[1]
    rows: list[dict[str, Any]] = []
    try:
        with path.open('r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fns = list(reader.fieldnames or [])
            have_ce = 'ce' in fns
            have_pe = 'pe' in fns
            have_idx = 'index_price' in fns
            have_iv = ('ce_iv' in fns) or ('pe_iv' in fns)
            have_greeks = any(c in fns for c in (
                'ce_delta','pe_delta','ce_theta','pe_theta','ce_vega','pe_vega','ce_gamma','pe_gamma','ce_rho','pe_rho'
            ))
            for r in reader:
                ts_s = parse_time_any(str(r.get('timestamp', '')).strip())
                ts_ms = parse_time_epoch_ms(str(r.get('timestamp', '')).strip())
                obj: dict[str, Any] = {'time': ts_ms, 'ts': ts_ms, 'time_str': ts_s, 'time_epoch_s': int(ts_ms / 1000) if ts_ms else None}
                for col in ('tp','avg_tp'):
                    val = r.get(col)
                    if val is None or val == '':
                        obj[col] = None
                    else:
                        try:
                            obj[col] = float(val)
                        except Exception:
                            obj[col] = None
                if have_ce:
                    try:
                        obj['ce'] = float(str(r.get('ce')))
                    except Exception:
                        obj['ce'] = None
                if have_pe:
                    try:
                        obj['pe'] = float(str(r.get('pe')))
                    except Exception:
                        obj['pe'] = None
                if have_idx:
                    try:
                        obj['index_price'] = float(str(r.get('index_price')))
                    except Exception:
                        obj['index_price'] = None
                if have_iv:
                    for col in ('ce_iv', 'pe_iv'):
                        v = r.get(col)
                        if v is None or v == '':
                            obj[col] = None
                        else:
                            try:
                                obj[col] = float(str(v))
                            except Exception:
                                obj[col] = None
                if have_greeks:
                    for col in (
                        'ce_delta','pe_delta','ce_theta','pe_theta',
                        'ce_vega','pe_vega','ce_gamma','pe_gamma','ce_rho','pe_rho'
                    ):
                        v = r.get(col)
                        if v is None or v == '':
                            obj[col] = None
                        else:
                            try:
                                obj[col] = float(str(v))
                            except Exception:
                                obj[col] = None
                rows.append(obj)
        try:
            def _ts_key_val(rv: Any) -> int:
                try:
                    if rv is None:
                        return -1
                    return int(rv)
                except Exception:
                    return -1
            rows.sort(key=lambda r: _ts_key_val(r.get('ts')))
        except Exception:
            pass
    except Exception:
        rows = []
    try:
        # evict if needed then cache
        if CSV_CACHE_MAX > 0:
            try:
                while len(_CSV_CACHE) >= CSV_CACHE_MAX and _CSV_CACHE:
                    _CSV_CACHE.popitem(last=False)
            except Exception:
                pass
            _CSV_CACHE[path] = (mtime_ns, rows)
    except Exception:
        pass
    return rows
