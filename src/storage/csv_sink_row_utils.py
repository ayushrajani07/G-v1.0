from __future__ import annotations

from typing import Any


def align_row_to_header(
    file_header: list[str],
    row: list[Any],
    header: list[str],
) -> list[Any]:
    """Align a single row to an existing file header, adding derived columns.

    This is a pure helper extracted from `CsvSink._align_row_to_header`.

    Current derivation behavior (legacy):
    - If `atm` exists in `file_header` but not in `header`, derive it as
      `strike - offset` (float conversions, best-effort).
    - For other unknown extra columns, append an empty placeholder.

    On conversion/shape errors, returns the original row.
    """

    try:
        mapping = {h: row[i] for i, h in enumerate(header) if i < len(row)}
        out: list[Any] = []
        for col in file_header:
            if col in mapping:
                out.append(mapping[col])
            elif col == "atm":
                try:
                    strike = float(mapping.get("strike", 0))
                    offset_raw = mapping.get("offset", 0)
                    offset = float(offset_raw) if isinstance(offset_raw, (int, float, str)) else 0.0
                    out.append(strike - offset)
                except (ValueError, TypeError):
                    out.append(0.0)
            else:
                out.append("")
        return out
    except (ValueError, TypeError):
        return list(row)


def reorder_time_columns(
    header: list[str],
    row: list[Any],
    *,
    file_exists: bool,
) -> tuple[list[str], list[Any]]:
    """Move `time` and `time_ms` to the end when creating a new file.

    Pure helper extracted from `CsvSink._reorder_time_columns`.

    - If `file_exists=True`, returns inputs unchanged.
    - If `file_exists=False` and both columns exist, returns a new header/row
      with those columns in the final two positions.

    On errors, returns inputs unchanged.
    """

    if file_exists:
        return header, row

    try:
        if "time" in header and "time_ms" in header:
            time_idx = header.index("time")
            time_ms_idx = header.index("time_ms")
            time_val = row[time_idx]
            time_ms_val = row[time_ms_idx]
            new_header = [c for c in header if c not in ("time", "time_ms")]
            new_row = [row[i] for i, c in enumerate(header) if c not in ("time", "time_ms")]
            new_header.extend(["time", "time_ms"])
            new_row.extend([time_val, time_ms_val])
            return new_header, new_row
    except (AttributeError, TypeError, KeyError, IndexError):
        return header, row

    return header, row
