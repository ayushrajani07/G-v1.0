from __future__ import annotations


def normalize_index(index: str | None, *, default: str = "NIFTY") -> str:
    """Normalize index query parameters.

    - Uppercases and trims whitespace.
    - Defensively collapses placeholder/template values like `${index}` to `default`.

    This keeps endpoint behavior stable even when Grafana/Infinity variables are
    copy/pasted into URLs.
    """

    idx_norm = (index or default).strip().upper()
    if any(ch in idx_norm for ch in ("$", "{", "}")):
        return default
    return idx_norm


__all__ = ["normalize_index"]
