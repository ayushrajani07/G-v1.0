import datetime as _dt

from src.storage.csv_sink_tp_utils import (
    compute_tp_change_metrics,
    parse_date_key_from_ts_str_rounded,
)


def test_parse_date_key_from_ts_str_rounded_valid() -> None:
    assert parse_date_key_from_ts_str_rounded("06-02-2026 09:15:30") == "2026-02-06"


def test_parse_date_key_from_ts_str_rounded_invalid_uses_fallback() -> None:
    fb = _dt.date(2020, 1, 2)
    assert parse_date_key_from_ts_str_rounded("not-a-timestamp", fallback=fb) == "2020-01-02"


def test_compute_tp_change_metrics_happy_path() -> None:
    net, day, net_pct, day_pct = compute_tp_change_metrics(tp_price=110.0, prev_tp_close=100.0, open_tp=105.0)
    assert net == 10.0
    assert day == 5.0
    assert net_pct == 10.0
    assert abs(day_pct - (5.0 / 105.0 * 100.0)) < 1e-9


def test_compute_tp_change_metrics_zero_denominators_are_safe() -> None:
    net, day, net_pct, day_pct = compute_tp_change_metrics(tp_price=110.0, prev_tp_close=0.0, open_tp=0.0)
    assert net == 110.0
    assert day == 110.0
    assert net_pct == 0.0
    assert day_pct == 0.0


def test_compute_tp_change_metrics_none_denominators_are_safe() -> None:
    net, day, net_pct, day_pct = compute_tp_change_metrics(tp_price=110.0, prev_tp_close=None, open_tp=None)
    assert net == 0.0
    assert day == 0.0
    assert net_pct == 0.0
    assert day_pct == 0.0
