"""Universal expiry resolution (single source of truth).

Rules (based solely on provider candidate dates):
- this_week  : nearest future expiry (minimum >= today)
- next_week  : 2nd nearest future expiry (falls back to nearest if only one)
- this_month : nearest monthly expiry (last expiry of a month among future dates)
- next_month : 2nd nearest monthly expiry (falls back to the first if none)

This module intentionally avoids weekday/holiday inference. Any holiday
adjustments must already be reflected in the provider-supplied candidate
date list. DTE (days-to-expiry) is a post-resolution concern.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
try:
    from src.utils.index_registry import get_index_meta  # provides weekly_dow per index
except Exception:  # pragma: no cover
    get_index_meta = None  # type: ignore

__all__ = [
    "normalize_rule",
    "select_expiry",
    "select_expiry_for_index",
]


def normalize_rule(rule: str) -> str:
    """Normalize user-facing rule strings to canonical tokens.

    Maps common aliases and formatting variants to:
      this_week | next_week | this_month | next_month
    """
    r = (rule or "").strip().lower().replace("-", "_")
    alias = {
        "current_week": "this_week",
        "following_week": "next_week",
        "current_month": "this_month",
        "following_month": "next_month",
        "next_nonth": "next_month",  # tolerate common typo
    }
    return alias.get(r, r)


def _future_sorted(candidates: Iterable[_dt.date], today: _dt.date) -> list[_dt.date]:
    return sorted(d for d in candidates if isinstance(d, _dt.date) and d >= today)


def _monthly_anchors(expiries: list[_dt.date]) -> list[_dt.date]:
    """Return last expiry per (year, month) from an ascending list of future dates."""
    month_last: dict[tuple[int, int], _dt.date] = {}
    for d in expiries:
        month_last[(d.year, d.month)] = d  # last assignment wins because expiries is ascending
    return sorted(month_last.values())


def _last_weekday_of_month(year: int, month: int, weekday: int) -> _dt.date:
    """Return the date for the last given weekday of a month (0=Mon .. 6=Sun)."""
    # Jump to first day of next month, then step backwards to desired weekday
    if month == 12:
        ny, nm = year + 1, 1
    else:
        ny, nm = year, month + 1
    first_next = _dt.date(ny, nm, 1)
    # Step back one day to get last day of current month
    last_current = first_next - _dt.timedelta(days=1)
    delta = (last_current.weekday() - weekday) % 7
    return last_current - _dt.timedelta(days=delta)


def select_expiry(candidates: Iterable[_dt.date], rule: str, *, today: _dt.date | None = None) -> _dt.date:
    """Resolve a concrete expiry date from a candidate set and a rule.

    Args:
        candidates: Iterable of candidate expiry dates (any order)
        rule: One of this_week, next_week, this_month, next_month (aliases allowed)
        today: Reference date; defaults to date.today()

    Raises:
        ValueError: If no future candidates are available or rule is unknown
    """
    t = today or _dt.date.today()
    expiries = _future_sorted(candidates, t)
    if not expiries:
        raise ValueError("no future expiries available")

    r = normalize_rule(rule)

    if r == "this_week":
        return expiries[0]
    if r == "next_week":
        if len(expiries) < 2:
            raise ValueError("next_week requires at least two future expiries")
        return expiries[1]

    months = _monthly_anchors(expiries)
    if not months:
        # degenerate case: fall back to weekly semantics
        return expiries[0]

    if r == "this_month":
        return months[0]
    if r == "next_month":
        return months[1] if len(months) >= 2 else months[0]

    raise ValueError(f"unknown expiry rule: {rule}")


def select_expiry_for_index(index_symbol: str, candidates: Iterable[_dt.date], rule: str, *, today: _dt.date | None = None) -> _dt.date:
    """Index-aware selection that can impose index-specific constraints.

        Current policy:
            - All indices support weekly and monthly rules (this_week/next_week, this_month/next_month).
            - Monthly anchor preference (as per explicit policy):
                    * NIFTY, BANKNIFTY, FINNIFTY: Last Tuesday of the month
                    * SENSEX: Last Thursday of the month
                We first try the computed "last weekday of month" if that exact date exists among
                provider candidates; otherwise we fall back to the provider-derived monthly anchor
                (last candidate within the month). If no anchor exists for the target month, use the
                nearest future monthly anchor from the candidate list (first or second as applicable).
    """
    idx = (index_symbol or "").upper()
    r = normalize_rule(rule)
    t = today or _dt.date.today()
    # Reduce to future set once
    future = _future_sorted(candidates, t)
    if not future:
        raise ValueError("no future expiries available")
    # Weekly rules are allowed for indices that request them via config; selection stays strict.
    # Important: Filter to WEEKLY candidates only (match index's weekly DOW) so
    # monthly anchors don't interfere with weekly selection.
    if r in {"this_week", "next_week"}:
        # Determine weekly weekday per index (explicit policy for SENSEX=Thu as well)
        weekly_dow = None
        if idx in {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"}:
            # Prefer registry when available
            try:
                if get_index_meta is not None:
                    weekly_dow = int(get_index_meta(idx).weekly_dow)
            except Exception:
                weekly_dow = None
            # Explicit overrides if registry unavailable or incorrect
            if weekly_dow is None:
                override = {
                    "NIFTY": 3,       # Thu
                    "BANKNIFTY": 2,   # Wed
                    "FINNIFTY": 1,    # Tue
                    "SENSEX": 3,      # Thu
                    "MIDCPNIFTY": 3,  # Thu
                }
                weekly_dow = override.get(idx, 3)
        # Filter future list to weekly-only candidates
        weekly_only = [d for d in future if weekly_dow is None or d.weekday() == weekly_dow]
        if not weekly_only:
            # Strict policy: do not resolve weekly using non-weekly dates.
            # Let the resolver fabricate weekly candidates or surface an error upstream.
            raise ValueError("no weekly candidates available for this index")
        if r == "this_week":
            return weekly_only[0]
        # next_week
        if len(weekly_only) < 2:
            # In no case should next_week resolve to weekly_only[0]
            raise ValueError("next_week requires at least two weekly candidates")
        return weekly_only[1]
    # Monthly anchor helpers
    months = _monthly_anchors(future)
    month_last_map = {(d.year, d.month): d for d in future}
    # Monthly weekday preference per requested policy:
    # NIFTY/BANKNIFTY/FINNIFTY -> last Tuesday (1)
    # SENSEX -> last Thursday (3)
    preferred_weekday = None
    if idx in {"NIFTY", "BANKNIFTY", "FINNIFTY"}:
        preferred_weekday = 1  # Tuesday
    elif idx in {"SENSEX"}:
        preferred_weekday = 3  # Thursday
    if r == "this_month":
        # Preferred: last weekday-of-month for CURRENT month if present in candidates
        if preferred_weekday is not None:
            target_this = _last_weekday_of_month(t.year, t.month, preferred_weekday)
            if target_this in future:
                return target_this
            # New policy: if not present, move on to last weekday of NEXT month
            nm_year = t.year + (1 if t.month == 12 else 0)
            nm_month = 1 if t.month == 12 else (t.month + 1)
            target_next = _last_weekday_of_month(nm_year, nm_month, preferred_weekday)
            if target_next in future:
                return target_next
        # Fallback preference: provider-derived anchor for NEXT month if available,
        # else any nearest monthly anchor (keeps behavior predictable when exact weekdays are absent)
        nm_year = t.year + (1 if t.month == 12 else 0)
        nm_month = 1 if t.month == 12 else (t.month + 1)
        anchor_next = month_last_map.get((nm_year, nm_month))
        if anchor_next:
            return anchor_next
        return months[0] if months else future[0]
    if r == "next_month":
        nm_year = t.year + (1 if t.month == 12 else 0)
        nm_month = 1 if t.month == 12 else (t.month + 1)
        if preferred_weekday is not None:
            target = _last_weekday_of_month(nm_year, nm_month, preferred_weekday)
            if target in future:
                return target
        anchor = month_last_map.get((nm_year, nm_month))
        if anchor:
            return anchor
        # Fallback: second monthly anchor if available, else the first
        if len(months) >= 2:
            return months[1]
        return months[0] if months else future[min(1, len(future)-1)]
    # Others fall back to generic selection on the full future set
    return select_expiry(future, r, today=t)
