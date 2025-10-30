"""Compatibility shim.

The canonical expiry rule mapping lives in src.utils.expiry_dates. This module
re-exports the public API to avoid breaking older imports and to keep a single
source of truth.
"""
from __future__ import annotations

try:
    from src.utils.expiry_dates import normalize_rule, select_expiry  # type: ignore F401
except Exception:  # pragma: no cover
    # Extremely minimal fallback to avoid import failures in constrained envs
    import datetime as _dt
    from collections.abc import Iterable

    def normalize_rule(rule: str) -> str:  # type: ignore
        return (rule or '').strip().lower().replace('-', '_')

    def select_expiry(expiries_iter: Iterable[_dt.date], rule: str, *, today: _dt.date | None = None) -> _dt.date:  # type: ignore
        today = today or _dt.date.today()
        expiries: list[_dt.date] = sorted(d for d in expiries_iter if isinstance(d, _dt.date) and d >= today)
        if not expiries:
            raise ValueError("no future expiries available")
        r = normalize_rule(rule)
        if r == 'next_week' and len(expiries) > 1:
            return expiries[1]
        return expiries[0]

__all__ = ["normalize_rule", "select_expiry"]
