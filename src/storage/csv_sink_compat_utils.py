from __future__ import annotations

import datetime
import json
from pathlib import Path
import re
from typing import Any


def compute_pcr(options_data: dict[str, dict[str, Any]]) -> float:
    """Compute Put/Call OI ratio.

    Mirrors legacy inline logic: sum PE oi / sum CE oi; ignores malformed entries.
    Returns 0.0 if CE OI aggregate is zero or missing.
    """

    try:
        put_oi = 0.0
        call_oi = 0.0
        for data in options_data.values():
            try:
                typ = (data.get("instrument_type") or "").upper()
                raw_oi = data.get("oi", 0)
                oi_val = (
                    float(raw_oi)
                    if isinstance(raw_oi, (int, float))
                    or (isinstance(raw_oi, str) and raw_oi.replace(".", "", 1).isdigit())
                    else 0.0
                )
                if typ == "PE":
                    put_oi += oi_val
                elif typ == "CE":
                    call_oi += oi_val
            except (ValueError, TypeError):
                continue
        return put_oi / call_oi if call_oi > 0 else 0.0
    except (ValueError, TypeError):
        return 0.0


def build_return_metrics(
    *,
    expiry_code: str,
    pcr: float,
    timestamp: datetime.datetime,
    day_width: float,
    index_price: float,
    flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build metrics payload filtering out falsey flags (legacy helper)."""

    payload: dict[str, Any] = {
        "expiry_code": expiry_code,
        "pcr": float(pcr),
        "timestamp": timestamp,
        "day_width": float(day_width),
        "index_price": float(index_price),
    }
    if flags:
        for k, v in flags.items():
            if v:
                payload[k] = True
    return payload


def compute_change_metrics(
    *,
    current: float,
    prev_close: float | None,
    open_value: float | None,
) -> tuple[float, float, float, float]:
    """Compute net/day absolute and percentage changes with zero/None guards."""

    try:
        net = float(current - float(prev_close)) if isinstance(prev_close, (int, float)) else 0.0
    except (ValueError, TypeError):
        net = 0.0
    try:
        day = float(current - float(open_value)) if isinstance(open_value, (int, float)) else 0.0
    except (ValueError, TypeError):
        day = 0.0
    net_pct = (
        (net / float(prev_close) * 100.0)
        if isinstance(prev_close, (int, float)) and float(prev_close) != 0.0
        else 0.0
    )
    day_pct = (
        (day / float(open_value) * 100.0)
        if isinstance(open_value, (int, float)) and float(open_value) != 0.0
        else 0.0
    )
    return net, day, net_pct, day_pct


def build_misclass_quarantine_record(
    *,
    ts: Any,
    index: Any,
    original_code: Any,
    canonical_code: Any,
    expiry_str: Any,
    offset: Any,
    index_price: Any,
    atm_strike: Any,
) -> dict[str, Any]:
    """Build an expiry misclassification quarantine record (legacy helper)."""

    try:
        offset_i = int(float(offset))
    except (ValueError, TypeError):
        offset_i = 0
    try:
        index_price_f = float(index_price)
    except (ValueError, TypeError):
        index_price_f = 0.0
    try:
        atm_strike_f = float(atm_strike)
    except (ValueError, TypeError):
        atm_strike_f = 0.0

    return {
        "ts": str(ts),
        "index": str(index) if index is not None else "",
        "original_expiry_code": str(original_code) if original_code is not None else "",
        "canonical_expiry_code": str(canonical_code) if canonical_code is not None else "",
        "reason": "expiry_misclassification",
        "row": {
            "expiry_date": str(expiry_str) if expiry_str is not None else "",
            "offset": offset_i,
            "index_price": index_price_f,
            "atm_strike": atm_strike_f,
        },
    }


def determine_expiry_code(exp_date: datetime.date, today: datetime.date | None = None) -> str:
    """Classify an expiry date into a logical expiry tag.

    Mirrors legacy CsvSink logic:
    - <= 7 days: this_week
    - <= 14 days: next_week
    - same month: this_month
    - otherwise: next_month
    """

    today = today or datetime.date.today()
    days_to_expiry = (exp_date - today).days
    if days_to_expiry <= 7:
        return "this_week"
    if days_to_expiry <= 14:
        return "next_week"
    if exp_date.month == today.month:
        return "this_month"
    return "next_month"


def prune_mixed_expiry_instruments(
    options_data: dict[str, dict[str, Any]],
    *,
    expected_expiry: datetime.date,
) -> int:
    """Remove option legs whose embedded expiry doesn't match the expected expiry date.

    Pure helper extracted from CsvSink._prune_mixed_expiry.
    Mutates options_data in place and returns number of dropped instruments.
    """

    dropped = 0
    for sym, data in list(options_data.items()):
        try:
            raw_exp = data.get("expiry") or data.get("expiry_date") or data.get("instrument_expiry")
            if not raw_exp:
                continue
            if isinstance(raw_exp, datetime.datetime):
                cand_date = raw_exp.date()
            elif isinstance(raw_exp, datetime.date):
                cand_date = raw_exp
            else:
                cand_date = None
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
                    try:
                        cand_date = datetime.datetime.strptime(str(raw_exp), fmt).date()
                        break
                    except (ValueError, TypeError):
                        continue
                if cand_date is None:
                    continue
            if cand_date != expected_expiry:
                options_data.pop(sym, None)
                dropped += 1
        except (KeyError, AttributeError, ValueError, TypeError):
            continue
    return dropped


def validate_grouped_strike_schema(strike_data: dict[float, dict[str, Any]]) -> list[str]:
    """Validate strike->leg map structure and prune invalid entries.

    Pure helper extracted from CsvSink._validate_schema.
    - Removes strikes <= 0
    - Drops legs where instrument_type is not CE/PE
    Mutates strike_data in place and returns issue identifiers.
    """

    schema_issues: list[str] = []
    for strike_key, leg_map in list(strike_data.items()):
        try:
            if strike_key <= 0:
                schema_issues.append(f"invalid_strike:{strike_key}")
                strike_data.pop(strike_key, None)
                continue
            for leg_type in ("CE", "PE"):
                leg = leg_map.get(leg_type)
                if leg:
                    inst_type = (leg.get("instrument_type") or "").upper()
                    if inst_type not in ("CE", "PE"):
                        schema_issues.append(f"missing_or_bad_type:{strike_key}:{leg_type}")
                        leg_map[leg_type] = None
        except (TypeError, KeyError, AttributeError, ValueError):
            continue
    return schema_issues


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_expiry_to_date(expiry: Any) -> datetime.date:
    """Parse an expiry value into a date.

    Mirrors legacy CsvSink logic:
    - If already a date, return as-is
    - Else parse YYYY-MM-DD from string

    Raises ValueError/TypeError/AttributeError on failures so the caller can
    preserve legacy exception handling and logging.
    """

    if isinstance(expiry, datetime.date):
        return expiry
    return datetime.datetime.strptime(str(expiry), "%Y-%m-%d").date()


def normalize_expiry_rule_tag(expiry_rule_tag: Any) -> str | None:
    """Normalize and validate an expiry_rule_tag.

    Returns a stripped string, or None if missing/empty.
    """

    if isinstance(expiry_rule_tag, str):
        s = expiry_rule_tag.strip()
        return s if s else None
    return None


def is_iso_date_tag(tag: Any) -> bool:
    """True if tag looks like a raw ISO date (YYYY-MM-DD)."""

    return isinstance(tag, str) and _ISO_DATE_RE.fullmatch(tag) is not None


def expected_expiry_tags_from_config(config: Any, *, index: str) -> set[str]:
    """Extract configured logical expiries for an index from a loaded config dict.

    Returns an empty set if the structure is missing/malformed.
    """

    try:
        if not isinstance(config, dict):
            return set()
        indices_cfg = config.get("indices", {})
        if not isinstance(indices_cfg, dict):
            return set()
        idx_cfg = indices_cfg.get(index, {})
        if not isinstance(idx_cfg, dict):
            return set()
        exp_list = idx_cfg.get("expiries")
        if isinstance(exp_list, list):
            out: set[str] = set()
            for x in exp_list:
                if isinstance(x, str) and x.strip():
                    out.add(x.strip())
            return out
        return set()
    except (TypeError, ValueError, AttributeError, KeyError):
        return set()


def compute_missing_expiry_advisory(
    *,
    seen: set[str],
    expected: set[str],
) -> set[str]:
    """Compute which expected expiry tags are missing given a seen set."""

    try:
        return set(expected) - set(seen)
    except (TypeError, ValueError):
        return set()


def should_emit_missing_expiry_advisory(
    *,
    seen: set[str],
    expected: set[str],
    already_emitted: bool,
) -> tuple[bool, set[str]]:
    """Return (should_emit, missing) for the one-shot missing-expiry advisory."""

    if already_emitted:
        return False, set()
    if not expected:
        return False, set()
    missing = compute_missing_expiry_advisory(seen=seen, expected=expected)
    if missing and len(seen) >= 1:
        return True, missing
    return False, set()


def g6_config_json_path_from_module_file(module_file: str) -> str:
    """Compute repo-root config/g6_config.json path from a module __file__."""

    try:
        # csv_sink.py lives at <root>/src/storage/csv_sink.py
        root = Path(module_file).resolve().parents[2]
        return str(root / "config" / "g6_config.json")
    except (OSError, RuntimeError, ValueError, TypeError):
        # Fallback to a relative path
        return str(Path("config") / "g6_config.json")


def load_json_file(path: str) -> Any | None:
    """Best-effort JSON loader.

    Returns parsed JSON or None on I/O/parse failure.
    """

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, PermissionError, FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return None


def allowed_expiry_tags_list_from_config(config: Any, *, index: str) -> list[str]:
    """Return configured allowed expiry tags for an index (as a list).

    Mirrors legacy enforcement behavior, preserving list ordering from config.
    """

    try:
        if not isinstance(config, dict):
            return []
        indices_cfg = config.get("indices", {})
        if not isinstance(indices_cfg, dict):
            return []
        idx_cfg = indices_cfg.get(index, {})
        if not isinstance(idx_cfg, dict):
            return []
        exp_list = idx_cfg.get("expiries")
        if not isinstance(exp_list, list):
            return []
        out: list[str] = []
        for x in exp_list:
            if isinstance(x, str):
                s = x.strip()
                if s:
                    out.append(s)
        return out
    except (TypeError, ValueError, AttributeError, KeyError):
        return []


def is_expiry_tag_disallowed(*, expiry_code: str, allowed: list[str]) -> bool:
    """Return True if allowed list is non-empty and expiry_code is not in it."""

    try:
        return bool(allowed) and expiry_code not in allowed
    except (TypeError, ValueError):
        return False


def build_disallowed_expiry_skipped_metrics(*, expiry_code: str, timestamp: datetime.datetime) -> dict[str, Any]:
    """Build the exact legacy skipped metrics payload for disallowed expiry tags."""

    return {
        "expiry_code": expiry_code,
        "pcr": 0,
        "timestamp": timestamp,
        "day_width": 0,
        "skipped": True,
    }


def resolve_index_price(
    *,
    index: str,
    index_price: float | None,
    options_data: dict[str, dict[str, Any]],
) -> float:
    """Resolve index price using legacy defaults and optional options_data override.

    Mirrors CsvSink.write_options_data behavior:
    - If index_price is truthy, use it
    - Else use per-index defaults, but prefer the first leg that contains 'index_price'
    """

    if index_price:
        return float(index_price)

    defaults = {
        "NIFTY": 24800,
        "BANKNIFTY": 54200,
        "FINNIFTY": 25900,
        "MIDCPNIFTY": 22000,
        "SENSEX": 80900,
    }
    resolved = float(defaults.get(index, 0))
    for data in options_data.values():
        if "index_price" in data:
            resolved = float(data["index_price"])
            break
    return resolved


def compute_pcr_strict_from_oi(options_data: dict[str, dict[str, Any]]) -> float:
    """Compute PCR using strict float conversion, matching legacy inline sums.

    This mirrors the write_options_data implementation:
    - Sum float(oi) for PE legs / sum float(oi) for CE legs
    - If CE sum is 0, returns 0.0
    - Raises if float conversion fails (behavior-preserving)
    """

    put_oi = sum(
        float(data.get("oi", 0))
        for data in options_data.values()
        if data.get("instrument_type") == "PE"
    )
    call_oi = sum(
        float(data.get("oi", 0))
        for data in options_data.values()
        if data.get("instrument_type") == "CE"
    )
    return put_oi / call_oi if call_oi > 0 else 0.0


def is_expiry_date_disallowed(*, exp_date: datetime.date, allowed_expiry_dates: Any) -> bool:
    """Return True if allowed_expiry_dates is a non-empty set/list/tuple and exp_date not in it."""

    if not allowed_expiry_dates:
        return False
    try:
        if isinstance(allowed_expiry_dates, (set, list, tuple)):
            return exp_date not in allowed_expiry_dates
    except (TypeError, KeyError, AttributeError, ValueError):
        return False
    return False


def build_invalid_expiry_date_skipped_metrics(
    *,
    expiry_code: str,
    timestamp: datetime.datetime,
) -> dict[str, Any]:
    """Build the exact legacy skipped metrics payload for invalid expiry dates."""

    return {
        "expiry_code": expiry_code,
        "pcr": 0,
        "timestamp": timestamp,
        "day_width": 0,
        "skipped_invalid_expiry": True,
    }


def select_nearest_atm_last_price(
    *,
    options_data: dict[str, dict[str, Any]],
    atm_strike: float,
    instrument_type: str,
) -> float:
    """Pick last_price for the option leg whose strike is closest to atm_strike.

    Mirrors legacy nested `_nearest_price` behavior:
    - Only considers legs with matching instrument_type
    - Strike parse failures are ignored (skipped)
    - last_price parse failures prevent that candidate from being selected
    - Returns 0.0 if nothing usable found
    """

    best_diff: float | None = None
    best_price = 0.0
    for od in options_data.values():
        if od.get("instrument_type") != instrument_type:
            continue
        try:
            k = float(od.get("strike", 0) or 0)
        except (TypeError, ValueError):
            continue
        except (OverflowError, RuntimeError):
            continue
        diff = abs(k - atm_strike)
        if best_diff is None or diff < best_diff:
            try:
                best_price = float(od.get("last_price", 0) or 0)
                best_diff = diff
            except (TypeError, ValueError):
                # Do not update best_diff if price is unusable
                pass
            except (OverflowError, RuntimeError):
                pass
    return best_price


def update_daily_open_tracking(
    *,
    stored_date_key: str | None,
    stored_open_value: float | None,
    date_key: str,
    current_time: datetime.time,
    current_value: float,
    market_open_time: datetime.time = datetime.time(9, 15),
    market_open_window_end: datetime.time = datetime.time(9, 30),
) -> tuple[str, float]:
    """Update (date_key, open_value) tracking with legacy market-open window semantics.

    Mirrors CsvSink.write_options_data behavior:
    - On a new date_key, always set open_value to current_value (regardless of time)
    - On the same date_key, only update open_value during the open window
    - Outside the window, keep stored_open_value (fallback to current_value if missing)
    """

    if stored_date_key != date_key:
        return date_key, float(current_value)

    if market_open_time <= current_time <= market_open_window_end:
        return date_key, float(current_value)

    if stored_open_value is None:
        return date_key, float(current_value)

    return date_key, float(stored_open_value)


def compute_net_and_day_changes(
    *,
    current_value: float,
    prev_close_value: float | None,
    day_open_value: float | None,
    day_open_fallback: float,
) -> tuple[float, float]:
    """Compute (net_change, day_change) matching CsvSink.write_options_data behavior.

    - net_change uses prev_close_value if present else 0.0
    - day_change subtracts day_open_value if present, else day_open_fallback
    """

    net_change = float(current_value) - float(prev_close_value) if prev_close_value is not None else 0.0
    open_val = day_open_value if day_open_value is not None else day_open_fallback
    day_change = float(current_value) - float(open_val)
    return net_change, day_change


def select_row_closest_to_time(
    *,
    rows: Any,
    target_time: datetime.time,
    timestamp_key: str = "timestamp",
    formats: tuple[str, ...] = ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M"),
) -> dict[str, Any] | None:
    """Select the row whose parsed timestamp time is closest to target_time.

    Mirrors the legacy logic in CsvSink._ensure_prev_close_loaded:
    - Tries multiple timestamp formats
    - Tracks the minimum absolute difference to target_time
    - If timestamp parsing fails for a row, uses that row as a fallback (overwrites closest)
    """

    closest_row: dict[str, Any] | None = None
    min_time_diff: float | None = None
    base_date = datetime.date(2000, 1, 1)

    for r in rows:
        try:
            ts_str = r.get(timestamp_key, "")  # type: ignore[union-attr]
            if not ts_str:
                continue
            row_time: datetime.time | None = None
            for fmt in formats:
                try:
                    dt = datetime.datetime.strptime(ts_str, fmt)
                    row_time = dt.time()
                    break
                except ValueError:
                    continue
            if row_time:
                time_diff = abs(
                    (
                        datetime.datetime.combine(base_date, row_time)
                        - datetime.datetime.combine(base_date, target_time)
                    ).total_seconds()
                )
                if min_time_diff is None or time_diff < min_time_diff:
                    min_time_diff = time_diff
                    closest_row = r
        except (KeyError, TypeError, ValueError):
            # If timestamp parsing fails, keep last row as fallback (legacy behavior)
            closest_row = r

    return closest_row


def parse_prev_close_values_from_overview_row(
    row: dict[str, Any],
    *,
    index_price_key: str = "index_price",
    tp_key: str = "tp",
) -> tuple[float | None, float | None]:
    """Parse (prev_idx_close, prev_tp_close) from an overview CSV row.

    Mirrors CsvSink._ensure_prev_close_loaded behavior:
    - index_price is expected
    - tp may be absent on older schemas
    - conversion failures yield None (not 0.0)
    """

    prev_idx_close: float | None
    prev_tp_close: float | None
    try:
        prev_idx_close = float(row.get(index_price_key, "") or 0.0)
    except (ValueError, TypeError):
        prev_idx_close = None
    try:
        prev_tp_close = float(row.get(tp_key, "") or 0.0)
    except (ValueError, TypeError):
        prev_tp_close = None
    return prev_idx_close, prev_tp_close


__all__ = [
    "compute_pcr",
    "build_return_metrics",
    "compute_change_metrics",
    "build_misclass_quarantine_record",
    "determine_expiry_code",
    "prune_mixed_expiry_instruments",
    "validate_grouped_strike_schema",
    "parse_expiry_to_date",
    "normalize_expiry_rule_tag",
    "is_iso_date_tag",
    "expected_expiry_tags_from_config",
    "compute_missing_expiry_advisory",
    "should_emit_missing_expiry_advisory",
    "g6_config_json_path_from_module_file",
    "load_json_file",
    "allowed_expiry_tags_list_from_config",
    "is_expiry_tag_disallowed",
    "build_disallowed_expiry_skipped_metrics",
    "resolve_index_price",
    "compute_pcr_strict_from_oi",
    "is_expiry_date_disallowed",
    "build_invalid_expiry_date_skipped_metrics",
    "select_nearest_atm_last_price",
    "update_daily_open_tracking",
    "compute_net_and_day_changes",
    "select_row_closest_to_time",
    "parse_prev_close_values_from_overview_row",
]
