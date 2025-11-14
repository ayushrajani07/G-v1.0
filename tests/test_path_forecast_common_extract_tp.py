from src.path_forecast.common import extract_tp

# Minimal tests for extract_tp synonyms coverage and ce+pe aggregation

def test_extract_tp_direct_tp():
    assert extract_tp({"tp": 123.4}) == 123.4
    assert extract_tp({"tp": "123.4"}) == 123.4


def test_extract_tp_avg_tp_fallback():
    assert extract_tp({"avg_tp": 55}) == 55
    # tp should take precedence over avg_tp
    assert extract_tp({"tp": 10, "avg_tp": 55}) == 10


def test_extract_tp_total_premium_synonyms():
    for key in ["tp_total", "total_premium", "straddle_premium", "atm_straddle"]:
        d = {key: 99.0}
        assert extract_tp(d) == 99.0


def test_extract_tp_ce_pe_variants():
    row = {"ce": 40.0, "pe": 60.0}
    assert extract_tp(row) == 100.0
    row2 = {"ce_ltp": 41.0, "put_ltp": 59.0}
    assert extract_tp(row2) == 100.0
    row3 = {"call": 25.5, "atm_put": 74.5}
    assert extract_tp(row3) == 100.0


def test_extract_tp_negative_clamped():
    assert extract_tp({"tp": -5}) == 0.0
    assert extract_tp({"ce": -10, "pe": 15}) == 5.0  # ce negative clamped to 0, sum => 0 + 15


def test_extract_tp_missing_returns_none():
    assert extract_tp({"ce": 10}) is None  # need both legs for aggregation when direct fields absent
    assert extract_tp({"random": 1}) is None

