"""Structured concise rolling log stream formatting.

Goal: produce single-line, information-dense records emitted each cycle / per-index
so that: (a) human tail in terminal is useful, (b) future dashboard can parse
directly without needing Prometheus scrape for basic stream view.

Log Line Types (prefix token):
  CYCLE  - one per completed overall collection cycle
  INDEX  - one per index after its expiries processed
  ERROR  - error events (optional enrichment)

Format (KEY=VAL space-delimited, no spaces in values; predictable ordering):
  CYCLE ts=1699999999 dur=1.42 opts=12345 opts_per_min=521.3 cpu=12.4 mem_mb=512.3
        api_ms=83.1 api_succ=99.2 coll_succ=97.5 indices=4 stall=0
  INDEX ts=1699999999 idx=NIFTY legs=345 succ=92.5 legs_avg=312 legs_cum=123456
        attempts=4 fail=0 age_s=0 pcr=1.02 atm=22450 err=none status=ok

Parsing: split once on first space for type token, then key=value pairs.
Durable: avoid removal of keys; add new keys at end to preserve backward compat.
"""
from __future__ import annotations

import re
import time
from typing import Any

from src.utils.color import colorize, severity_color

try:  # optional (avoid import cycles for lightweight use)
    from src.config.env_config import EnvConfig
except Exception:  # pragma: no cover
    EnvConfig = None  # type: ignore

ISO_TS = False  # if True, include human time; keep false for headless ingestion


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _visible_len(s: str) -> int:
    return len(_ANSI_RE.sub("", s))


def _pad_visible(s: str, width: int, *, align: str = "left") -> str:
    """Pad a string to a visible width, ignoring ANSI escape sequences."""
    if width <= 0:
        return s
    vis = _visible_len(s)
    pad = max(0, width - vis)
    if pad == 0:
        return s
    if align == "right":
        return (" " * pad) + s
    if align == "center":
        left = pad // 2
        right = pad - left
        return (" " * left) + s + (" " * right)
    return s + (" " * pad)

def _ts() -> str:
    now = time.time()
    return str(int(now)) if not ISO_TS else time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now))

def format_cycle(
    *,
    duration_s: float,
    options: int,
    options_per_min: float | None,
    cpu: float | None,
    mem_mb: float | None,
    api_latency_ms: float | None,
    api_success_pct: float | None,
    collection_success_pct: float | None,
    indices: int,
    stall_flag: int | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    parts = ["CYCLE", f"ts={_ts()}"]
    parts.append(f"dur={duration_s:.2f}")
    parts.append(f"opts={options}")
    if options_per_min is not None:
        parts.append(f"opts_per_min={options_per_min:.1f}")
    if cpu is not None:
        parts.append(f"cpu={cpu:.1f}")
    if mem_mb is not None:
        parts.append(f"mem_mb={mem_mb:.1f}")
    if api_latency_ms is not None:
        parts.append(f"api_ms={api_latency_ms:.1f}")
    if api_success_pct is not None:
        parts.append(f"api_succ={api_success_pct:.1f}")
    if collection_success_pct is not None:
        parts.append(f"coll_succ={collection_success_pct:.1f}")
    parts.append(f"indices={indices}")
    if stall_flag is not None:
        parts.append(f"stall={stall_flag}")
    if extra:
        for k,v in extra.items():
            # sanitize spaces
            if isinstance(v, float):
                parts.append(f"{k}={v:.3f}")
            else:
                parts.append(f"{k}={v}")
    return ' '.join(parts)

def format_index(
    *,
    index: str,
    legs: int,
    legs_avg: float | None,
    legs_cum: int | None,
    succ_pct: float | None,
    succ_avg_pct: float | None,
    attempts: int | None,
    failures: int | None,
    last_age_s: float | None,
    pcr: float | None,
    atm: float | None,
    err: str | None,
    status: str,
    extra: dict[str, Any] | None = None,
) -> str:
    parts = ["INDEX", f"ts={_ts()}", f"idx={index}", f"legs={legs}"]
    if legs_avg is not None:
        parts.append(f"legs_avg={int(legs_avg)}")
    if legs_cum is not None:
        parts.append(f"legs_cum={legs_cum}")
    if succ_pct is not None:
        parts.append(f"succ={succ_pct:.1f}")
    if succ_avg_pct is not None:
        parts.append(f"succ_avg={succ_avg_pct:.1f}")
    if attempts is not None:
        parts.append(f"attempts={attempts}")
    if failures is not None:
        parts.append(f"fail={failures}")
    if last_age_s is not None:
        parts.append(f"age_s={int(last_age_s)}")
    if pcr is not None:
        parts.append(f"pcr={pcr:.2f}")
    if atm is not None:
        parts.append(f"atm={int(atm)}")
    parts.append(f"err={(err or 'none')}")
    parts.append(f"status={status}")
    if extra:
        for k,v in extra.items():
            if isinstance(v, float):
                parts.append(f"{k}={v:.3f}")
            else:
                parts.append(f"{k}={v}")
    return ' '.join(parts)

def format_start(*, version: str, indices: int, interval_s: int, concise: bool, extra: dict[str, Any] | None = None) -> str:
    parts = ["START", f"ts={_ts()}", f"ver={version}", f"indices={indices}", f"interval_s={interval_s}", f"concise={'1' if concise else '0'}"]
    if extra:
        for k,v in extra.items():
            if isinstance(v, float):
                parts.append(f"{k}={v:.3f}")
            else:
                parts.append(f"{k}={v}")
    return ' '.join(parts)

def format_cycle_pretty(*,
    duration_s: float,
    options: int,
    options_per_min: float | None,
    cpu: float | None,
    mem_mb: float | None,
    api_latency_ms: float | None,
    api_success_pct: float | None,
    collection_success_pct: float | None,
    indices: int,
    stall_flag: int | None = None,
) -> str:
    """Return a human-friendly multi-metric summary line for a cycle.

    Includes anomaly flags:
      - NO_DATA when options == 0
      - DEGRADED when success rates < 90% (api or collection)
      - STALL when stall_flag is truthy
    """
    status_tokens: list[str] = []
    if options == 0:
        status_tokens.append('NO_DATA')
    if (api_success_pct is not None and api_success_pct < 90) or (collection_success_pct is not None and collection_success_pct < 90):
        status_tokens.append('DEGRADED')
    if stall_flag:
        status_tokens.append('STALL')
    if not status_tokens:
        status_tokens.append('OK')
    status = '+'.join(status_tokens)
    # Build aligned columns
    opm = f"{options_per_min:.1f}" if options_per_min is not None else '-'
    cpu_str = f"{cpu:.1f}%" if cpu is not None else '-'
    mem_str = f"{mem_mb:.1f}MB" if mem_mb is not None else '-'
    api_ms = f"{api_latency_ms:.1f}ms" if api_latency_ms is not None else '-'
    api_s = f"{api_success_pct:.1f}%" if api_success_pct is not None else '-'
    coll_s = f"{collection_success_pct:.1f}%" if collection_success_pct is not None else '-'
    stall = str(stall_flag) if stall_flag is not None else '-'
    return (
        f"CYCLE_SUMMARY dur={duration_s:.2f}s opts={options} opm={opm} api={api_ms} api_succ={api_s} "
        f"coll_succ={coll_s} cpu={cpu_str} mem={mem_str} indices={indices} stall={stall} status={status}"
    )

def format_cycle_table(*,
    duration_s: float,
    options: int,
    options_per_min: float | None,
    cpu: float | None,
    mem_mb: float | None,
    api_latency_ms: float | None,
    api_success_pct: float | None,
    collection_success_pct: float | None,
    indices: int,
    stall_flag: int | None = None,
) -> tuple[str, str]:
    """Return (header_line, value_line) for cycle metrics.

    Logged separately so each line carries its own timestamp / logger prefix for readability.
    """
    status_tokens: list[str] = []
    if options == 0:
        status_tokens.append('NO_DATA')
    if (api_success_pct is not None and api_success_pct < 90) or (collection_success_pct is not None and collection_success_pct < 90):
        status_tokens.append('DEGRADED')
    if stall_flag:
        status_tokens.append('STALL')
    if not status_tokens:
        status_tokens.append('OK')
    status = '+'.join(status_tokens)

    # In human mode, default to the compact table shown in operator screenshots.
    # Can be overridden with G6_CYCLE_TABLE_COMPACT=0/1.
    human_mode = False
    compact = False
    try:
        if EnvConfig is not None:
            human_mode = EnvConfig.get_bool('G6_HUMAN_MODE', False)
            compact = EnvConfig.get_bool('G6_CYCLE_TABLE_COMPACT', human_mode)
    except Exception:
        compact = False

    # Prepare raw values (without units for sizing)
    if compact:
        row = {
            'Dur(s)': f"{duration_s:.2f}",
            'Opts': str(options),
            'Opm': f"{options_per_min:.1f}" if options_per_min is not None else '-',
            'API(ms)': f"{api_latency_ms:.1f}" if api_latency_ms is not None else '-',
            'Coll%': f"{collection_success_pct:.1f}" if collection_success_pct is not None else '-',
            'Status': status,
        }
    else:
        row = {
            'Dur(s)': f"{duration_s:.2f}",
            'Opts': str(options),
            'OpM': f"{options_per_min:.1f}" if options_per_min is not None else '-',
            'API(ms)': f"{api_latency_ms:.1f}" if api_latency_ms is not None else '-',
            'API%': f"{api_success_pct:.1f}" if api_success_pct is not None else '-',
            'Coll%': f"{collection_success_pct:.1f}" if collection_success_pct is not None else '-',
            'CPU%': f"{cpu:.1f}" if cpu is not None else '-',
            'Mem(MB)': f"{mem_mb:.1f}" if mem_mb is not None else '-',
            'Idx': str(indices),
            'Stall': str(stall_flag) if stall_flag is not None else '-',
            'Status': status,
        }
    headers = list(row.keys())
    # Compute widths
    widths = {h: max(len(h), len(row[h])) for h in headers}

    numeric_cols = {
        'Dur(s)', 'Opts', 'OpM', 'Opm', 'OpM', 'API(ms)', 'API%', 'Coll%', 'CPU%', 'Mem(MB)', 'Idx', 'Stall'
    }

    # Build header line (simple; no ANSI)
    header_cells = []
    for h in headers:
        align = "right" if h in numeric_cols else "left"
        header_cells.append(_pad_visible(h, widths[h], align=align))
    header_line = ' '.join(header_cells)

    # Apply color AFTER width calc so we don't distort alignment.
    value_cells = []
    for h in headers:
        raw_val = row[h]
        val = raw_val
        if h == 'Status':
            col, bold = severity_color(raw_val)
            val = colorize(raw_val, col, bold=bold)
        align = "right" if h in numeric_cols else "left"
        value_cells.append(_pad_visible(val, widths[h], align=align))
    value_line = ' '.join(value_cells)
    return header_line, value_line


def format_indices_table(indices: list[dict[str, Any]], *, max_rows: int = 8) -> str:
    """Human-friendly compact per-index table (best-effort fields).

    Intended for terminal readability; safe to call even with partial/missing keys.
    """
    rows: list[dict[str, str]] = []
    for ix in (indices or [])[:max_rows]:
        try:
            name = str(ix.get('index') or ix.get('idx') or ix.get('name') or '?')
            status = str(ix.get('status') or 'unknown')
            err = str(ix.get('error') or ix.get('err') or 'none')
            if not err or err.lower() in ('none', 'null', 'nan'):
                err = 'none'

            # legs/options
            legs = ix.get('option_count')
            if not isinstance(legs, (int, float)):
                try:
                    legs = sum(int(e.get('options') or 0) for e in (ix.get('expiries') or []) if isinstance(e, dict))
                except Exception:
                    legs = 0

            attempts = ix.get('attempts')
            # Some paths store attempts/failures per expiry; keep best-effort fallbacks.
            if not isinstance(attempts, (int, float)):
                attempts = ix.get('attempts_total') or ix.get('attempts_sum') or '-'

            atm = ix.get('atm') or ix.get('atm_strike')
            strike_cov = ix.get('strike_coverage_avg') or ix.get('strike_coverage')

            # If not present at index-level, compute from expiry list.
            if not isinstance(strike_cov, (int, float)):
                try:
                    vals = []
                    for e in (ix.get('expiries') or []):
                        if not isinstance(e, dict):
                            continue
                        v = e.get('strike_coverage')
                        if isinstance(v, (int, float)):
                            vals.append(float(v))
                    if vals:
                        strike_cov = sum(vals) / len(vals)
                except Exception:
                    pass

            def _fmt_cov(v: Any) -> str:
                if isinstance(v, (int, float)):
                    # Support both 0..1 and 0..100
                    vv = float(v)
                    if vv <= 1.0:
                        vv *= 100.0
                    return f"{vv:.0f}%" if vv >= 10 else f"{vv:.1f}%"
                return '-'

            rows.append({
                'Idx': name,
                'Legs': str(int(legs) if isinstance(legs, (int, float)) else legs),
                'Att': str(int(attempts) if isinstance(attempts, (int, float)) else attempts),
                'CovS': _fmt_cov(strike_cov),
                'ATM': str(int(atm)) if isinstance(atm, (int, float)) else '-',
                'Status': status,
                'Err': err if err else 'none',
            })
        except Exception:
            continue

    if not rows:
        return "INDICES (none)"

    # Drop Err column if everything is 'none' (common case).
    any_err = any((r.get('Err') or 'none').lower() not in ('none', '-') for r in rows)
    headers = ['Idx', 'Legs', 'Att', 'CovS', 'ATM', 'Status'] + (['Err'] if any_err else [])
    widths = {h: len(h) for h in headers}
    for r in rows:
        for h in headers:
            widths[h] = max(widths[h], len(str(r.get(h, ''))))

    numeric = {'Legs', 'Att', 'CovS', 'ATM'}
    header_line = ' '.join(_pad_visible(h, widths[h], align=('right' if h in numeric else 'left')) for h in headers)

    out_lines = ["INDICES", header_line]
    for r in rows:
        status_raw = r.get('Status', 'unknown')
        status_colored = status_raw
        try:
            col, bold = severity_color(status_raw)
            status_colored = colorize(status_raw, col, bold=bold)
        except Exception:
            pass
        cells = []
        for h in headers:
            v = status_colored if h == 'Status' else str(r.get(h, ''))
            cells.append(_pad_visible(v, widths[h], align=('right' if h in numeric else 'left')))
        out_lines.append(' '.join(cells))
    return "\n".join(out_lines)

__all__ = [
    'format_cycle', 'format_index', 'format_start', 'format_cycle_pretty', 'format_cycle_table', 'format_cycle_readable', 'format_indices_table'
]

def format_cycle_readable(*,
    duration_s: float,
    options: int,
    options_per_min: float | None,
    cpu: float | None,
    mem_mb: float | None,
    api_latency_ms: float | None,
    api_success_pct: float | None,
    collection_success_pct: float | None,
    indices: int,
    stall_flag: int | None = None,
) -> str:
    """Return a human-readable single line summary (no abbreviations).

    Example:
      CYCLE_READABLE duration=0.82s options=410 (per_min=1023.4) api_latency=83.1ms api_success=99.2% collection_success=98.7% cpu=12.4% mem=512.3MB indices=4 stall=- status=OK

    Keeps machine-friendly key=value pairs while improving clarity for operators.
    """
    status_tokens: list[str] = []
    if options == 0:
        status_tokens.append('NO_DATA')
    if (api_success_pct is not None and api_success_pct < 90) or (collection_success_pct is not None and collection_success_pct < 90):
        status_tokens.append('DEGRADED')
    if stall_flag:
        status_tokens.append('STALL')
    if not status_tokens:
        status_tokens.append('OK')
    status = '+'.join(status_tokens)
    parts = ["CYCLE_READABLE"]
    parts.append(f"duration={duration_s:.2f}s")
    parts.append(f"options={options}")
    if options_per_min is not None:
        parts.append(f"per_min={options_per_min:.1f}")
    if api_latency_ms is not None:
        parts.append(f"api_latency={api_latency_ms:.1f}ms")
    if api_success_pct is not None:
        parts.append(f"api_success={api_success_pct:.1f}%")
    if collection_success_pct is not None:
        parts.append(f"collection_success={collection_success_pct:.1f}%")
    if cpu is not None:
        parts.append(f"cpu={cpu:.1f}%")
    if mem_mb is not None:
        parts.append(f"mem={mem_mb:.1f}MB")
    parts.append(f"indices={indices}")
    parts.append(f"stall={stall_flag if stall_flag is not None else '-'}")
    parts.append(f"status={status}")
    return ' '.join(parts)
