from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

# Smoke test with faked collaborators to validate one-index happy path shape

def test_pipeline_smoke_one_index(monkeypatch):
    from src.collectors.modules import pipeline as pl

    # Fake providers with minimal surface used by pipeline
    class FakeProviders:
        def get_atm_strike(self, index: str):
            return 100.0
        def get_instruments(self, index: str):
            # Pipeline only needs a non-empty list for build_expiry_map
            return [{'symbol': f'{index}_OPT'}]

    fp = FakeProviders()

    # Fake build_expiry_map -> single expiry today with same list
    def fake_build_expiry_map(instruments):
        return {dt.date.today(): instruments}, {'count': len(instruments)}

    # Fake compute_strike_universe -> three strikes
    def fake_compute_strike_universe(atm, itm, otm, index, scale=None):
        return [ATM_ROUND(atm-50), ATM_ROUND(atm), ATM_ROUND(atm+50)], {'itm': itm, 'otm': otm}

    def ATM_ROUND(x):
        return int(round(float(x)))

    # Fake enrichers / coverage
    def fake_enrich_quotes(index, rule, expiry_date, exp_instruments, providers, metrics):
        # one CE one PE minimal fields
        return {
            'CE': {'last_price': 1.0},
            'PE': {'last_price': 1.2},
        }

    def fake_cov_metrics(ctx, exp_instruments, strikes, index_symbol, rule, expiry_date):
        return {'strike_coverage': 1.0}

    def fake_field_cov(ctx, enriched, index_symbol, rule, expiry_date):
        return {'field_coverage': 1.0}

    def fake_adaptive_post_expiry(ctx, index_symbol, expiry_rec, rule):
        return None

    # Apply monkeypatches on the pipeline module symbols
    monkeypatch.setattr(pl, 'build_expiry_map', fake_build_expiry_map, raising=True)
    monkeypatch.setattr(pl, 'compute_strike_universe', fake_compute_strike_universe, raising=True)
    monkeypatch.setattr(pl, 'enrich_quotes', fake_enrich_quotes, raising=True)
    monkeypatch.setattr(pl, 'coverage_metrics', fake_cov_metrics, raising=True)
    monkeypatch.setattr(pl, 'field_coverage_metrics', fake_field_cov, raising=True)
    monkeypatch.setattr(pl, 'adaptive_post_expiry', fake_adaptive_post_expiry, raising=True)

    res = pl.run_pipeline(
        index_params={'NIFTY': {'strikes_itm': 1, 'strikes_otm': 1, 'expiries': ['this_week']}},
        providers=fp,
        csv_sink=None, metrics=SimpleNamespace(),
        build_snapshots=False,
        legacy_baseline=None,
    )

    assert res['status'] == 'ok'
    assert res['indices_processed'] == 1
    assert isinstance(res['indices'], list) and len(res['indices']) == 1
    idx = res['indices'][0]
    assert idx['index'] == 'NIFTY'
    assert idx['status'] in ('OK', 'EMPTY')
    assert isinstance(idx['expiries'], list) and len(idx['expiries']) >= 1
    exp0 = idx['expiries'][0]
    assert exp0['rule'] in ('this_week', 'monthly')
    assert 'strike_coverage' in exp0 and 'field_coverage' in exp0
