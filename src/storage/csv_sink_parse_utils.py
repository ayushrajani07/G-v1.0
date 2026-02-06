from __future__ import annotations

from typing import Any


def get_float(d: dict[str, Any] | None, k: str, default: float = 0.0) -> float:
    """Best-effort float getter for option dicts.

    Extracted from `CsvSink._prepare_option_row`'s legacy inline helper.
    - If `d` is None: returns default
    - Otherwise: tries `float(d.get(k, default))`
    - On ValueError/TypeError: returns default
    """

    try:
        return float(d.get(k, default)) if d else default
    except (ValueError, TypeError):
        return default


def get_int(d: dict[str, Any] | None, k: str, default: int = 0) -> int:
    """Best-effort int getter for option dicts.

    Extracted from `CsvSink._prepare_option_row`'s legacy inline helper.
    - If `d` is None: returns default
    - Otherwise: tries `int(d.get(k, default))`
    - On ValueError/TypeError: returns default
    """

    try:
        return int(d.get(k, default)) if d else default
    except (ValueError, TypeError):
        return default
