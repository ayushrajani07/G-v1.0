from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable


def resolve_live_csv_path(
    *,
    project_root: Path,
    idx_norm: str,
    expiry_tag: str,
    offset: str,
    day: date,
    find_live_csv: Callable[[Path, str, str, str, date], Path | None],
) -> Path | None:
    """Resolve the live CSV path for a route.

    Primary path is `data/g6_data/<IDX>/<expiry>/<offset>/<YYYY-MM-DD>.csv` via
    `find_live_csv`. A flat fallback is supported for tests:
      - `data/g6_data/<IDX>_<expiry>_<offset>.csv`
      - `data/g6_data/<IDX>_<expiry>_+<offset>.csv` (if numeric)

    Returns a Path only if the candidate exists on disk.
    """

    base = project_root / "data" / "g6_data"
    p: Path | None
    try:
        p = find_live_csv(base, idx_norm, expiry_tag, offset, day)
    except (AttributeError, TypeError, ValueError, OSError):
        p = None

    if p and p.exists():
        return p

    try:
        flat = base / f"{idx_norm}_{expiry_tag}_{offset}.csv"
        if flat.exists():
            return flat
        if offset and offset.isdigit():
            flat2 = base / f"{idx_norm}_{expiry_tag}_+{offset}.csv"
            if flat2.exists():
                return flat2
    except (OSError, PermissionError, ValueError, TypeError):
        pass

    return None


__all__ = ["resolve_live_csv_path"]
