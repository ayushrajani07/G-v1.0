from __future__ import annotations

from typing import Optional

from fastapi import Request

from .._date_norm import resolve_date
from .._now_norm import clamp_ms_to_rows, extract_now_override_raw, parse_int_ms


def load_live_rows_and_context_impl(
    request: Request,
    idx_norm: str,
    expiry_tag: str,
    offset: str,
    date_str: Optional[str],
    now_override_ms: Optional[str],
    *,
    normalize_expiry_tag,
    project_root,
    find_live_csv,
    load_csv_rows_full,
    row_time_ms,
    extract_tp,
):
    """Shared loader extracted from router.

    Kept as a plain function (not a FastAPI route) so tests can still monkeypatch
    the router-level indirection function.
    """

    # Resolve the effective date and load live CSV rows
    the_date = resolve_date(date_str)

    eff_tag = normalize_expiry_tag(idx_norm, expiry_tag)
    p = find_live_csv((project_root() / "data" / "g6_data"), idx_norm, eff_tag, offset, the_date)
    if not p or not p.exists():
        return None, None, None, eff_tag, the_date

    rows = load_csv_rows_full(p)
    if not rows:
        return [], None, None, eff_tag, the_date

    # Resolve ref time and last_tp with optional override
    last_tp: float | None = None
    ref_now_ms: int | None = None

    raw_override = (
        extract_now_override_raw(now_override_ms, request.query_params)
    )
    nm = parse_int_ms(raw_override)

    if nm is not None:
        try:
            nm = clamp_ms_to_rows(int(nm), rows)

            for r in reversed(rows):
                try:
                    ems = int(r.get("ts") or r.get("time") or 0)
                except (TypeError, ValueError):
                    continue
                if not ems or ems > nm:
                    continue
                tpv = extract_tp(r)
                if isinstance(tpv, (int, float)):
                    last_tp = float(tpv)
                    ref_now_ms = int(ems)
                    break
        except (TypeError, ValueError, IndexError, KeyError):
            pass

    if last_tp is None or ref_now_ms is None:
        for r in reversed(rows):
            ems = row_time_ms(r)
            if not isinstance(ems, int) or ems <= 0:
                continue
            tpv = extract_tp(r)
            if isinstance(tpv, (int, float)):
                last_tp = float(tpv)
                ref_now_ms = int(ems)
                break

    return rows, last_tp, ref_now_ms, eff_tag, the_date
