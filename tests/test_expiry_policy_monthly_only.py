import datetime as dt
import pytest

from src.utils.expiry_dates import select_expiry_for_index


def test_banknifty_weekly_rules_raise():
    today = dt.date.today()
    # Candidate expiries over next 90 days (Thursdays)
    # Build a simple weekly cadence list as candidates
    d = today
    while d.weekday() != 3:
        d += dt.timedelta(days=1)
    candidates = [d + dt.timedelta(days=7*i) for i in range(8)]

    with pytest.raises(ValueError):
        select_expiry_for_index("BANKNIFTY", candidates, "this_week", today=today)
    with pytest.raises(ValueError):
        select_expiry_for_index("BANKNIFTY", candidates, "next_week", today=today)


def test_finnifty_weekly_rules_raise():
    today = dt.date.today()
    d = today
    while d.weekday() != 1:  # Tuesdays for FINNIFTY typical weekly, but it shouldn't matter
        d += dt.timedelta(days=1)
    candidates = [d + dt.timedelta(days=7*i) for i in range(8)]

    with pytest.raises(ValueError):
        select_expiry_for_index("FINNIFTY", candidates, "this_week", today=today)
    with pytest.raises(ValueError):
        select_expiry_for_index("FINNIFTY", candidates, "next_week", today=today)


def test_monthly_rules_ok_for_banknifty_and_finnifty():
    today = dt.date.today()
    # Make a realistic candidate set including end-of-month anchors
    # Ensure at least two months present
    candidates = []
    base = dt.date(today.year, today.month, 1)
    for m in range(0, 3):
        y = base.year + (base.month + m - 1)//12
        mo = (base.month + m - 1) % 12 + 1
        # include a few scattered dates and ensure last Thursday/Tuesdays likely present
        for day in (10, 17, 24, 27, 28):
            try:
                candidates.append(dt.date(y, mo, day))
            except ValueError:
                continue
    # Should not raise for monthly rules
    for idx in ("BANKNIFTY", "FINNIFTY"):
        for rule in ("this_month", "next_month"):
            _ = select_expiry_for_index(idx, candidates, rule, today=today)
