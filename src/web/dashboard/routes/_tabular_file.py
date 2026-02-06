from __future__ import annotations

from pathlib import Path


def read_header_and_rows(path: Path, *, encoding: str = "utf-8") -> tuple[str, list[str]]:
    """Read a simple newline-delimited tabular file.

    Returns `(header_line, rows)` where `rows` are the remaining lines.
    If the file is empty, returns ("", []).

    Intentionally minimal: callers keep control of filtering and tailing order.
    """

    lines = path.read_text(encoding=encoding).splitlines()
    if not lines:
        return "", []
    return lines[0], lines[1:]


def tail_rows(rows: list[str], tail: int | None) -> list[str]:
    """Return the last `tail` rows, leaving ordering intact."""

    if tail is None:
        return rows
    try:
        n = int(tail)
    except (TypeError, ValueError):
        return rows
    if n <= 0:
        return []
    if len(rows) <= n:
        return rows
    return rows[-n:]


__all__ = ["read_header_and_rows", "tail_rows"]
