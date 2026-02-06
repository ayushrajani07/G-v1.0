from __future__ import annotations

import datetime as _dt


def rebuild_time_time_ms_from_timestamp(header: str, rows: list[str]) -> tuple[str, list[str]]:
    """Ensure `time` + `time_ms` columns exist and are derived from `timestamp`.

    This is used by Grafana Infinity queries which typically expect an ISO time column.

    Behavior is intentionally forgiving:
    - If there is no `timestamp` column, returns inputs unchanged.
    - If parsing fails for all rows, returns inputs unchanged.
    - If `time` already exists, it is rebuilt (and moved to first column) to avoid
      trusting potentially malformed upstream `time` values.
    """

    cols = (header or "").split(",") if header else []
    if "timestamp" not in cols:
        return header, rows

    has_time = "time" in cols
    ts_idx = cols.index("timestamp")
    cols_wo_time = [c for c in cols if c != "time"]
    new_cols = ["time", "time_ms"] + cols_wo_time

    def _parse_epoch_ms(value: str) -> int | None:
        s = (value or "").strip()
        if not s:
            return None

        # Common exporter formats
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%d-%m-%Y %H:%M:%S",
        ):
            try:
                dt = _dt.datetime.strptime(s, fmt)
                return int(dt.timestamp() * 1000)
            except (TypeError, ValueError):
                continue

        # Integer epoch seconds/millis
        try:
            if s.isdigit():
                if len(s) >= 13:
                    return int(s[:13])
                return int(s) * 1000
        except (TypeError, ValueError):
            pass
        return None

    out_lines: list[str] = [",".join(new_cols)]
    for r in rows:
        parts = r.split(",")
        if len(parts) <= ts_idx:
            continue
        ems = _parse_epoch_ms(parts[ts_idx])
        if ems is None:
            continue
        iso = _dt.datetime.fromtimestamp(ems / 1000).replace(microsecond=0).isoformat()

        if has_time:
            mapping = {name: parts[i] if i < len(parts) else "" for i, name in enumerate(cols)}
            reordered = [mapping.get(name, "") for name in cols_wo_time]
            out_lines.append(",".join([iso, str(ems), *reordered]))
        else:
            out_lines.append(f"{iso},{ems},{r}")

    # If we couldn't parse anything, keep original to avoid producing empty output.
    if len(out_lines) <= 1:
        return header, rows

    return out_lines[0], out_lines[1:]


__all__ = ["rebuild_time_time_ms_from_timestamp"]
