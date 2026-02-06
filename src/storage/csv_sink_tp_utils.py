from __future__ import annotations

import datetime as _dt


def parse_date_key_from_ts_str_rounded(ts_str_rounded: str, *, fallback: _dt.date | None = None) -> str:
    """Parse `YYYY-MM-DD` from `dd-mm-YYYY HH:MM:SS`.

    Falls back to `fallback` (or today's date) on malformed input.
    """
    try:
        if not isinstance(ts_str_rounded, str):
            raise TypeError("ts_str_rounded must be str")
        s = ts_str_rounded.strip()

        # Primary expected format
        try:
            dt = _dt.datetime.strptime(s, "%d-%m-%Y %H:%M:%S")
        except ValueError:
            # tolerate date-only inputs
            dt = _dt.datetime.strptime(s.split(" ", 1)[0], "%d-%m-%Y")

        return dt.date().isoformat()
    except (ValueError, IndexError, AttributeError, TypeError):
        return (fallback or _dt.date.today()).isoformat()


def compute_tp_change_metrics(
    *,
    tp_price: float,
    prev_tp_close: float | None,
    open_tp: float | None,
) -> tuple[float, float, float, float]:
    """Compute TP change metrics safely.

    Returns:
      (tp_net_change, tp_day_change, tp_net_change_pct, tp_day_change_pct)

    Percent changes are 0.0 when denominator is None/0.
    """
    prev = float(prev_tp_close) if prev_tp_close is not None else None
    open_val = float(open_tp) if open_tp is not None else None

    tp_net_change = float(tp_price) - float(prev) if prev is not None else 0.0
    tp_day_change = float(tp_price) - float(open_val) if open_val is not None else 0.0

    tp_net_change_pct = (tp_net_change / float(prev) * 100.0) if prev not in (None, 0.0) else 0.0
    tp_day_change_pct = (tp_day_change / float(open_val) * 100.0) if open_val not in (None, 0.0) else 0.0

    return tp_net_change, tp_day_change, tp_net_change_pct, tp_day_change_pct
