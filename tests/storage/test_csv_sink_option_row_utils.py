from __future__ import annotations

from src.storage.csv_sink_option_row_utils import build_option_row


def test_build_option_row_schema_and_values():
    header, row = build_option_row(
        ts_str_rounded="12-11-2025 09:30:00",
        index="NIFTY",
        expiry_code="this_week",
        expiry_date_str="2025-11-20",
        offset=50,
        index_price=24580.0,
        atm_strike=24550.0,
        offset_price=24600.0,
        ce_price=92.0,
        pe_price=108.0,
        tp_price=200.0,
        ce_avg=90.0,
        pe_avg=110.0,
        avg_tp=200.0,
        ce_vol=123,
        pe_vol=456,
        ce_oi=111,
        pe_oi=222,
        ce_iv=0.12,
        pe_iv=0.13,
        ce_delta=0.5,
        pe_delta=-0.4,
        ce_theta=-1.2,
        pe_theta=-1.1,
        ce_vega=2.0,
        pe_vega=2.1,
        ce_gamma=0.01,
        pe_gamma=0.02,
        ce_rho=0.3,
        pe_rho=-0.2,
        tp_net_change=10.0,
        tp_day_change=5.0,
        tp_net_change_pct=5.0,
        tp_day_change_pct=2.5,
    )

    # quick invariants
    assert header[:8] == [
        "timestamp",
        "index",
        "expiry_tag",
        "expiry_date",
        "offset",
        "index_price",
        "atm",
        "strike",
    ]
    assert len(header) == len(row)

    d = dict(zip(header, row))
    assert d["strike"] == 24600.0
    assert d["tp"] == 200.0
    assert d["tp_net_change"] == 10.0
    assert d["tp_day_change_pct"] == 2.5
    assert d["ce_gamma"] == 0.01
    assert d["pe_delta"] == -0.4
