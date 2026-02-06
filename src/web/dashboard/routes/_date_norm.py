from __future__ import annotations

from datetime import date


def resolve_date(date_str: str | None, *, default: date | None = None) -> date:
    """Resolve an optional YYYY-MM-DD override into a `datetime.date`.

    - If `date_str` is empty/None or invalid, returns `default` (or `date.today()`).
    - If `date_str` is valid ISO (YYYY-MM-DD), returns that date.

    Kept intentionally forgiving for dashboard query params.
    """

    fallback = default or date.today()
    try:
        if date_str:
            return date.fromisoformat(str(date_str))
    except (TypeError, ValueError):
        return fallback
    return fallback


__all__ = ["resolve_date"]
