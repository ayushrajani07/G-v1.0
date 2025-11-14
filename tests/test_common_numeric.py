from __future__ import annotations

import os
import math
from src.path_forecast.common import safe_int, safe_float, clamp, env_flag


def test_safe_int_basic():
    assert safe_int(5) == 5
    assert safe_int(5.7) == 5  # truncation
    assert safe_int("12") == 12
    assert safe_int("bad", 3) == 3


def test_safe_int_bounds():
    assert safe_int(100, 0, min_=10, max_=50) == 50  # upper clamp
    assert safe_int(1, 0, min_=10, max_=50) == 10    # lower clamp


def test_safe_float_basic():
    assert safe_float(1.25) == 1.25
    v = safe_float("2.5")
    assert v is not None and math.isclose(v, 2.5)
    assert safe_float("bad", None) is None


def test_safe_float_bounds():
    assert safe_float(100.0, 0.0, min_=10.0, max_=50.0) == 50.0
    assert safe_float(1.0, 0.0, min_=10.0, max_=50.0) == 10.0


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-5, 0, 10) == 0
    assert clamp(50, 0, 10) == 10


def test_env_flag_truthy_and_falsey(monkeypatch):
    monkeypatch.setenv("X_TEST_ON", "1")
    monkeypatch.setenv("X_TEST_OFF", "false")
    assert env_flag("X_TEST_ON") is True
    assert env_flag("X_TEST_OFF") is False
    assert env_flag("X_TEST_MISSING") is False

