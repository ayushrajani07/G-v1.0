from __future__ import annotations

from datetime import date

from src.web.dashboard.routes._date_norm import resolve_date


def test_resolve_date_valid_iso():
    assert resolve_date("2026-02-04", default=date(2020, 1, 1)) == date(2026, 2, 4)


def test_resolve_date_invalid_returns_default():
    assert resolve_date("not-a-date", default=date(2020, 1, 1)) == date(2020, 1, 1)


def test_resolve_date_none_returns_default():
    assert resolve_date(None, default=date(2020, 1, 1)) == date(2020, 1, 1)
