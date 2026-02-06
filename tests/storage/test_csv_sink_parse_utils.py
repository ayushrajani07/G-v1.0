from __future__ import annotations

from src.storage.csv_sink_parse_utils import get_float, get_int


def test_get_float_none_dict_returns_default():
    assert get_float(None, "x", 1.25) == 1.25


def test_get_float_parses_numeric_and_string():
    assert get_float({"v": 2}, "v") == 2.0
    assert get_float({"v": "3.5"}, "v") == 3.5


def test_get_float_bad_value_returns_default():
    assert get_float({"v": "abc"}, "v", 9.0) == 9.0


def test_get_int_none_dict_returns_default():
    assert get_int(None, "x", 7) == 7


def test_get_int_parses_numeric_and_string_int():
    assert get_int({"v": 10}, "v") == 10
    assert get_int({"v": "12"}, "v") == 12


def test_get_int_bad_value_returns_default():
    assert get_int({"v": "xyz"}, "v", 5) == 5
