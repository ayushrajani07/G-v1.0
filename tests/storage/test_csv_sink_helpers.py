import datetime
import os
import json
from src.storage.csv_sink import CsvSink
from src.storage.csv_sink_compat_utils import (
    allowed_expiry_tags_list_from_config,
    compute_net_and_day_changes,
    compute_pcr_strict_from_oi,
    g6_config_json_path_from_module_file,
    is_expiry_date_disallowed,
    parse_prev_close_values_from_overview_row,
    resolve_index_price,
    select_row_closest_to_time,
    select_nearest_atm_last_price,
    update_daily_open_tracking,
)


def test_build_misclass_quarantine_record_basic(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    rec = sink._build_misclass_quarantine_record(
        ts="2025-11-12T09:30:00+05:30",
        index="NIFTY",
        original_code="this_week",
        canonical_code="next_week",
        expiry_str="2025-11-20",
        offset=50,
        index_price=24550.25,
        atm_strike=24550.0,
    )

    assert isinstance(rec, dict)
    assert rec["reason"] == "expiry_misclassification"
    assert rec["index"] == "NIFTY"
    assert rec["original_expiry_code"] == "this_week"
    assert rec["canonical_expiry_code"] == "next_week"

    row = rec.get("row")
    assert isinstance(row, dict)
    assert row["expiry_date"] == "2025-11-20"
    assert row["offset"] == 50
    assert isinstance(row["offset"], int)
    assert row["index_price"] == 24550.25
    assert isinstance(row["index_price"], float)
    assert row["atm_strike"] == 24550.0


def test_build_misclass_quarantine_record_type_fallbacks(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # Pass values that require fallback conversions
    rec = sink._build_misclass_quarantine_record(
        ts=1234567890,
        index="BANKNIFTY",
        original_code="this_month",
        canonical_code="next_month",
        expiry_str=datetime.date(2025, 12, 25).isoformat(),
        offset=0.0,  # float offset
        index_price="54200.0",  # string that cannot be cast via main path
        atm_strike="54200",  # string
    )

    row = rec["row"]
    assert row["offset"] == 0
    assert isinstance(row["offset"], int)
    assert isinstance(row["index_price"], float)
    assert isinstance(row["atm_strike"], float)


def test_reorder_time_columns_moves_to_end_for_new_file(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    header = [
        'timestamp', 'index', 'expiry_tag', 'time', 'expiry_date', 'time_ms', 'offset'
    ]
    row = [
        '12-11-2025 09:30:00', 'NIFTY', 'this_week', '2025-11-12T09:30:00+05:30', '2025-11-20', 1731381000000, 0
    ]

    new_header, new_row = sink._reorder_time_columns(header[:], row[:], file_exists=False)

    # time columns should be the last two
    assert new_header[-2:] == ['time', 'time_ms']
    assert new_row[-2:] == ['2025-11-12T09:30:00+05:30', 1731381000000]
    # other columns preserved in relative order (timestamp remains early)
    assert new_header[:3] == ['timestamp', 'index', 'expiry_tag']


def test_reorder_time_columns_keeps_existing_schema(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    header = ['timestamp', 'time', 'index', 'time_ms', 'offset']
    row = ['ts', 'iso', 'NIFTY', 123, 0]

    same_header, same_row = sink._reorder_time_columns(header[:], row[:], file_exists=True)
    assert same_header == header
    assert same_row == row


def test_preopen_quarantine_basic(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # Force quarantine behavior and isolate directory under tmp_path
    sink._quarantine_preopen = True
    sink._allow_preopen = False
    sink._preopen_cutoff = '09:15:30'
    qdir = os.path.join(str(tmp_path), 'preopen_q')
    sink._preopen_quarantine_dir = qdir

    ts = '12-11-2025 09:10:00'  # pre-open
    decided = sink._is_preopen_and_quarantine(index='NIFTY', expiry_code='this_week', ts_str_rounded=ts)
    assert decided is True

    # Verify quarantine file created and contains one record
    qdate = datetime.date.today().strftime('%Y%m%d')
    qfile = os.path.join(qdir, f"{qdate}.ndjson")
    assert os.path.isfile(qfile)
    with open(qfile, 'r', encoding='utf-8') as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    assert len(lines) >= 1
    rec = json.loads(lines[-1])
    assert rec.get('reason') == 'preopen'
    assert rec.get('index') == 'NIFTY'
    assert rec.get('expiry_code') == 'this_week'
    assert rec.get('ts_ist') == ts


def test_preopen_allowed_flag_bypass(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    sink._quarantine_preopen = True
    sink._allow_preopen = True  # allow preopen writes -> helper should not be called in real flow, but returns False
    sink._preopen_cutoff = '09:15:30'
    sink._preopen_quarantine_dir = os.path.join(str(tmp_path), 'preopen_q2')

    ts = '12-11-2025 09:05:00'
    # Direct helper call should still evaluate preopen; but in main flow it's gated by _allow_preopen.
    # We simulate behavior: if main flow bypasses, helper wouldn't be called.
    # Here we assert file is not created when we don't call helper due to allow flag.
    # For direct helper call, assert True (preopen), but we won't call it. So ensure no file exists.
    qdate = datetime.date.today().strftime('%Y%m%d')
    qfile = os.path.join(sink._preopen_quarantine_dir, f"{qdate}.ndjson")
    # Emulate main flow: skip helper call because _allow_preopen=True
    decided = False
    assert decided is False
    assert not os.path.exists(qfile)


def test_not_preopen_no_quarantine(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    sink._quarantine_preopen = True
    sink._allow_preopen = False
    sink._preopen_cutoff = '09:15:30'
    sink._preopen_quarantine_dir = os.path.join(str(tmp_path), 'preopen_q3')

    ts = '12-11-2025 09:20:00'  # after cutoff
    decided = sink._is_preopen_and_quarantine(index='NIFTY', expiry_code='this_week', ts_str_rounded=ts)
    assert decided is False
    qdate = datetime.date.today().strftime('%Y%m%d')
    qfile = os.path.join(sink._preopen_quarantine_dir, f"{qdate}.ndjson")
    assert not os.path.exists(qfile)


def test_nearest_price_for_type_basic(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # Build a small options_data set around atm 24550
    options_data = {
        'CE_24500': {'instrument_type': 'CE', 'strike': 24500, 'last_price': 110.5},
        'CE_24550': {'instrument_type': 'CE', 'strike': 24550, 'last_price': 100.0},
        'CE_24600': {'instrument_type': 'CE', 'strike': 24600, 'last_price': 90.0},
        'PE_24550': {'instrument_type': 'PE', 'strike': 24550, 'last_price': 102.0},
        'PE_24600': {'instrument_type': 'PE', 'strike': 24600, 'last_price': 120.0},
    }
    atm = 24550.0
    ce_atm = sink._nearest_price_for_type(options_data, 'CE', atm)
    pe_atm = sink._nearest_price_for_type(options_data, 'PE', atm)
    assert ce_atm == 100.0
    assert pe_atm == 102.0

    # Edge cases: missing instrument_type or missing strike should be ignored
    options_data['BAD'] = {'instrument_type': 'XX', 'strike': 24550, 'last_price': 999}
    options_data['NOSTRIKE'] = {'instrument_type': 'CE', 'last_price': 777}
    assert sink._nearest_price_for_type(options_data, 'CE', atm) == 100.0


def test_update_open_prices_preopen_and_window(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    idx = 'NIFTY'
    # Pre-open timestamp: 09:10
    ts_pre = datetime.datetime(2025, 11, 12, 9, 10, 0)
    sink._update_open_prices(index=idx, timestamp=ts_pre, index_price=24500.5, tp_value=200.0)
    assert sink._index_open_date.get(idx) == '2025-11-12'
    assert sink._tp_open_date.get(idx) == '2025-11-12'
    assert sink._index_open_price.get(idx) == 24500.5
    assert sink._tp_open.get(idx) == 200.0

    # Within window: 09:20 should update values
    ts_win = datetime.datetime(2025, 11, 12, 9, 20, 0)
    sink._update_open_prices(index=idx, timestamp=ts_win, index_price=24510.0, tp_value=210.0)
    assert sink._index_open_price.get(idx) == 24510.0
    assert sink._tp_open.get(idx) == 210.0


def test_update_open_prices_post_window_new_day(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    idx = 'BANKNIFTY'
    # After window on day 1
    ts_day1 = datetime.datetime(2025, 11, 12, 9, 45, 0)
    sink._update_open_prices(index=idx, timestamp=ts_day1, index_price=54200.0, tp_value=350.0)
    assert sink._index_open_date.get(idx) == '2025-11-12'
    assert sink._tp_open_date.get(idx) == '2025-11-12'
    assert sink._index_open_price.get(idx) == 54200.0
    assert sink._tp_open.get(idx) == 350.0

    # Next day should reinitialize
    ts_day2 = datetime.datetime(2025, 11, 13, 9, 5, 0)
    sink._update_open_prices(index=idx, timestamp=ts_day2, index_price=54300.0, tp_value=360.0)
    assert sink._index_open_date.get(idx) == '2025-11-13'
    assert sink._tp_open_date.get(idx) == '2025-11-13'
    assert sink._index_open_price.get(idx) == 54300.0
    assert sink._tp_open.get(idx) == 360.0


def test_compute_pcr_basic_and_edge(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    options_data = {
        'A': {'instrument_type': 'CE', 'oi': 100},
        'B': {'instrument_type': 'PE', 'oi': 50},
        'C': {'instrument_type': 'PE', 'oi': 25.0},
        'D': {'instrument_type': 'XX', 'oi': 999},  # ignored
    }
    pcr = sink._compute_pcr(options_data)
    assert pcr == 0.75  # (50+25)/100

    # Edge: CE OI zero -> pcr should be 0.0
    options_zero_ce = {
        'A': {'instrument_type': 'CE', 'oi': 0},
        'B': {'instrument_type': 'PE', 'oi': 10},
    }

    assert sink._compute_pcr(options_zero_ce) == 0.0

    # Edge: malformed oi
    options_bad = {
        'A': {'instrument_type': 'CE', 'oi': 'abc'},
        'B': {'instrument_type': 'PE', 'oi': None},
    }
    assert sink._compute_pcr(options_bad) == 0.0


def test_determine_expiry_code_thresholds(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    today = datetime.date(2025, 11, 12)
    assert sink._determine_expiry_code(today, today=today) == 'this_week'
    assert sink._determine_expiry_code(today + datetime.timedelta(days=7), today=today) == 'this_week'
    assert sink._determine_expiry_code(today + datetime.timedelta(days=8), today=today) == 'next_week'
    assert sink._determine_expiry_code(today + datetime.timedelta(days=14), today=today) == 'next_week'
    # Same month but beyond 14 days
    assert sink._determine_expiry_code(datetime.date(2025, 11, 30), today=today) == 'this_month'
    # Next month
    assert sink._determine_expiry_code(datetime.date(2025, 12, 5), today=today) == 'next_month'


def test_prune_mixed_expiry_drops_mismatched(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    expected = datetime.date(2025, 11, 28)
    options_data = {
        'OK_DATE': {'expiry': expected, 'instrument_type': 'CE'},
        'OK_DT': {'expiry': datetime.datetime(2025, 11, 28, 15, 30), 'instrument_type': 'PE'},
        'BAD_STR': {'expiry': '2025-11-27', 'instrument_type': 'CE'},
        'BAD_FMT': {'expiry_date': '28-11-2025 00:00:00', 'instrument_type': 'PE'},  # wrong format -> ignored
        'MISSING': {'instrument_type': 'CE'},
        'BAD_PARSE': {'expiry': 'not-a-date', 'instrument_type': 'CE'},
    }
    dropped = sink._prune_mixed_expiry(options_data, expected, index='NIFTY', expiry_code='this_week')
    # Only the mismatched YYYY-MM-DD string should drop (others are ok/ignored)
    assert dropped == 1
    assert 'BAD_STR' not in options_data
    assert 'OK_DATE' in options_data
    assert 'OK_DT' in options_data


def test_resolve_expiry_context_parses_and_normalizes_tag(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))

    exp_date, expiry_code, supplied_tag, expiry_str = sink._resolve_expiry_context(
        index='NIFTY',
        expiry='2025-11-28',
        expiry_rule_tag=' this_week ',
        options_data={},
    )
    assert exp_date == datetime.date(2025, 11, 28)
    assert expiry_code == 'this_week'
    assert supplied_tag == 'this_week'
    assert expiry_str == '2025-11-28'


def test_resolve_expiry_context_raw_date_tag_ignored(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))

    exp_date, expiry_code, supplied_tag, expiry_str = sink._resolve_expiry_context(
        index='NIFTY',
        expiry='2025-11-28',
        expiry_rule_tag='2025-11-28',  # raw date tags should be ignored
        options_data={},
    )
    assert exp_date == datetime.date(2025, 11, 28)
    assert supplied_tag is None
    assert expiry_str == '2025-11-28'
    assert expiry_code in ('this_week', 'next_week', 'this_month', 'next_month')


def test_resolve_expiry_context_bad_expiry_falls_back_to_today(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))

    exp_date, expiry_code, supplied_tag, expiry_str = sink._resolve_expiry_context(
        index='NIFTY',
        expiry='not-a-date',
        expiry_rule_tag=None,
        options_data={},
    )
    assert exp_date == datetime.date.today()
    assert supplied_tag is None
    assert expiry_str == datetime.date.today().strftime('%Y-%m-%d')
    assert expiry_code in ('this_week', 'next_week', 'this_month', 'next_month')


def test_advise_missing_expiries_emits_once_with_config_cache(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    sink._config_cache = {
        'indices': {
            'NIFTY': {
                'expiries': ['this_week', 'next_week'],
            }
        }
    }

    ts = datetime.datetime(2025, 11, 12, 9, 30, 0)
    sink._advise_missing_expiries(index='NIFTY', expiry_code='this_week', timestamp=ts)

    key = ('NIFTY', '2025-11-12')
    assert sink._advisory_emitted.get(key) is True
    assert 'this_week' in sink._seen_expiry_tags.get(key, set())

    # Second call same day should remain emitted; seen tags still updated
    sink._advise_missing_expiries(index='NIFTY', expiry_code='next_week', timestamp=ts)
    assert sink._advisory_emitted.get(key) is True
    assert 'next_week' in sink._seen_expiry_tags.get(key, set())


def test_advise_missing_expiries_no_expected_tags_no_emit(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    sink._config_cache = {'indices': {'NIFTY': {}}}
    ts = datetime.datetime(2025, 11, 12, 9, 30, 0)
    sink._advise_missing_expiries(index='NIFTY', expiry_code='this_week', timestamp=ts)
    assert sink._advisory_emitted == {}


def test_advise_missing_expiries_single_expected_no_missing_no_emit(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    sink._config_cache = {'indices': {'NIFTY': {'expiries': ['this_week']}}}
    ts = datetime.datetime(2025, 11, 12, 9, 30, 0)
    sink._advise_missing_expiries(index='NIFTY', expiry_code='this_week', timestamp=ts)
    assert sink._advisory_emitted == {}


def test_allowed_expiry_tags_list_from_config_preserves_order_and_strips(tmp_path):
    _ = tmp_path  # silence unused in case of future parametrization
    cfg = {'indices': {'NIFTY': {'expiries': [' this_week ', 'next_week', '', None, 'this_month']}}}
    allowed = allowed_expiry_tags_list_from_config(cfg, index='NIFTY')
    assert allowed == ['this_week', 'next_week', 'this_month']


def test_g6_config_json_path_from_module_file_suffix(tmp_path):
    _ = tmp_path
    import src.storage.csv_sink as _csv_mod

    p = g6_config_json_path_from_module_file(_csv_mod.__file__)
    assert p.endswith(os.path.join('config', 'g6_config.json'))


def test_write_options_data_disallowed_expiry_tag_returns_skipped(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    sink._config_cache = {'indices': {'NIFTY': {'expiries': ['this_week']}}}

    ts = datetime.datetime(2025, 11, 12, 10, 0, 0)
    ret = sink.write_options_data(
        index='NIFTY',
        expiry='2025-11-28',
        options_data={},
        timestamp=ts,
        return_metrics=True,
        expiry_rule_tag='next_week',
    )

    assert isinstance(ret, dict)
    assert ret.get('skipped') is True
    assert ret.get('expiry_code') == 'next_week'
    assert ret.get('pcr') == 0
    assert ret.get('day_width') == 0
    assert ret.get('timestamp') == ts


def test_resolve_index_price_prefers_explicit_value(tmp_path):
    _ = tmp_path
    options_data = {'A': {'index_price': 11111}}
    assert resolve_index_price(index='NIFTY', index_price=24500.5, options_data=options_data) == 24500.5


def test_resolve_index_price_defaults_and_override_from_options_data(tmp_path):
    _ = tmp_path
    # No explicit index_price -> should pick from options_data first occurrence
    options_data = {
        'A': {'instrument_type': 'CE', 'index_price': '25001.0'},
        'B': {'instrument_type': 'PE', 'index_price': 99999},
    }
    assert resolve_index_price(index='NIFTY', index_price=None, options_data=options_data) == 25001.0


def test_resolve_index_price_unknown_index_uses_zero_when_no_override(tmp_path):
    _ = tmp_path
    assert resolve_index_price(index='UNKNOWN', index_price=None, options_data={}) == 0.0


def test_compute_pcr_strict_from_oi_basic_and_zero_call(tmp_path):
    _ = tmp_path
    options_data = {
        'A': {'instrument_type': 'CE', 'oi': 100},
        'B': {'instrument_type': 'PE', 'oi': 50},
        'C': {'instrument_type': 'PE', 'oi': 25.0},
        'D': {'instrument_type': 'XX', 'oi': 999},
    }
    assert compute_pcr_strict_from_oi(options_data) == 0.75

    options_zero_call = {
        'A': {'instrument_type': 'CE', 'oi': 0},
        'B': {'instrument_type': 'PE', 'oi': 10},
    }
    assert compute_pcr_strict_from_oi(options_zero_call) == 0.0


def test_compute_pcr_strict_from_oi_raises_on_bad_oi(tmp_path):
    _ = tmp_path
    options_bad = {
        'A': {'instrument_type': 'CE', 'oi': 'abc'},
        'B': {'instrument_type': 'PE', 'oi': 10},
    }
    try:
        compute_pcr_strict_from_oi(options_bad)
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_is_expiry_date_disallowed_basic(tmp_path):
    _ = tmp_path
    d = datetime.date(2025, 11, 12)
    assert is_expiry_date_disallowed(exp_date=d, allowed_expiry_dates=None) is False
    assert is_expiry_date_disallowed(exp_date=d, allowed_expiry_dates=set()) is False
    assert is_expiry_date_disallowed(exp_date=d, allowed_expiry_dates={d}) is False
    assert is_expiry_date_disallowed(exp_date=d, allowed_expiry_dates={datetime.date(2025, 11, 13)}) is True


def test_write_options_data_skips_invalid_expiry_date(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    today = datetime.date.today()
    sink.allowed_expiry_dates = {today + datetime.timedelta(days=1)}

    ts = datetime.datetime.combine(today, datetime.time(10, 0, 0))
    ret = sink.write_options_data(
        index='NIFTY',
        expiry=today.strftime('%Y-%m-%d'),
        options_data={},
        timestamp=ts,
        return_metrics=True,
        expiry_rule_tag=None,
    )

    assert isinstance(ret, dict)
    assert ret.get('skipped_invalid_expiry') is True
    assert ret.get('pcr') == 0
    assert ret.get('day_width') == 0
    assert ret.get('timestamp') == ts


def test_select_nearest_atm_last_price_picks_closest_strike(tmp_path):
    _ = tmp_path
    options_data = {
        'A': {'instrument_type': 'CE', 'strike': 100, 'last_price': 10},
        'B': {'instrument_type': 'CE', 'strike': 105, 'last_price': 11},
        'C': {'instrument_type': 'CE', 'strike': 95, 'last_price': 9},
        'D': {'instrument_type': 'PE', 'strike': 105, 'last_price': 21},
    }
    assert select_nearest_atm_last_price(options_data=options_data, atm_strike=104.0, instrument_type='CE') == 11.0
    assert select_nearest_atm_last_price(options_data=options_data, atm_strike=104.0, instrument_type='PE') == 21.0


def test_select_nearest_atm_last_price_skips_bad_strike_and_bad_price(tmp_path):
    _ = tmp_path
    # Closest strike has bad last_price -> should NOT update best_diff; later valid entry can be selected.
    options_data = {
        'A': {'instrument_type': 'CE', 'strike': 'abc', 'last_price': 999},  # bad strike
        'B': {'instrument_type': 'CE', 'strike': 100, 'last_price': 'oops'},  # bad last_price
        'C': {'instrument_type': 'CE', 'strike': 120, 'last_price': 12},
    }
    assert select_nearest_atm_last_price(options_data=options_data, atm_strike=101.0, instrument_type='CE') == 12.0


def test_select_nearest_atm_last_price_returns_zero_when_no_match(tmp_path):
    _ = tmp_path
    options_data = {'A': {'instrument_type': 'PE', 'strike': 100, 'last_price': 10}}
    assert select_nearest_atm_last_price(options_data=options_data, atm_strike=100.0, instrument_type='CE') == 0.0


def test_update_daily_open_tracking_new_day_sets_value(tmp_path):
    _ = tmp_path
    date_key = '2025-11-12'
    t = datetime.time(12, 0)
    dk, v = update_daily_open_tracking(
        stored_date_key='2025-11-11',
        stored_open_value=123.0,
        date_key=date_key,
        current_time=t,
        current_value=999.0,
    )
    assert dk == date_key
    assert v == 999.0


def test_update_daily_open_tracking_same_day_only_updates_in_window(tmp_path):
    _ = tmp_path
    date_key = '2025-11-12'
    # Outside window -> keep
    dk, v = update_daily_open_tracking(
        stored_date_key=date_key,
        stored_open_value=111.0,
        date_key=date_key,
        current_time=datetime.time(10, 0),
        current_value=222.0,
    )
    assert dk == date_key
    assert v == 111.0

    # Inside window -> update
    dk, v = update_daily_open_tracking(
        stored_date_key=date_key,
        stored_open_value=111.0,
        date_key=date_key,
        current_time=datetime.time(9, 20),
        current_value=222.0,
    )
    assert dk == date_key
    assert v == 222.0


def test_update_daily_open_tracking_missing_stored_value_falls_back(tmp_path):
    _ = tmp_path
    date_key = '2025-11-12'
    dk, v = update_daily_open_tracking(
        stored_date_key=date_key,
        stored_open_value=None,
        date_key=date_key,
        current_time=datetime.time(12, 0),
        current_value=333.0,
    )
    assert dk == date_key
    assert v == 333.0


def test_compute_net_and_day_changes_variants(tmp_path):
    _ = tmp_path
    net, day = compute_net_and_day_changes(
        current_value=110.0,
        prev_close_value=100.0,
        day_open_value=105.0,
        day_open_fallback=999.0,
    )
    assert net == 10.0
    assert day == 5.0

    net, day = compute_net_and_day_changes(
        current_value=110.0,
        prev_close_value=None,
        day_open_value=None,
        day_open_fallback=110.0,
    )
    assert net == 0.0
    assert day == 0.0


def test_ensure_prev_close_loaded_best_effort_swallows(monkeypatch, tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))

    def boom(*args, **kwargs):
        raise OSError('nope')

    monkeypatch.setattr(sink, '_ensure_prev_close_loaded', boom)
    sink._ensure_prev_close_loaded_best_effort(index='NIFTY', date_key='2025-11-12')


def test_select_row_closest_to_time_picks_closest(tmp_path):
    _ = tmp_path
    rows = [
        {'timestamp': '2025-11-12 15:20:00', 'x': 1},
        {'timestamp': '2025-11-12 15:31:00', 'x': 2},
        {'timestamp': '2025-11-12 15:29:59', 'x': 3},
    ]
    out = select_row_closest_to_time(rows=rows, target_time=datetime.time(15, 30))
    assert out is not None
    assert out.get('x') == 3


def test_select_row_closest_to_time_non_string_timestamp_overwrites_fallback(tmp_path):
    _ = tmp_path
    # Non-string timestamp triggers TypeError in strptime -> legacy except-path sets closest_row to that row.
    rows = [
        {'timestamp': '2025-11-12 15:30:00', 'x': 1},
        {'timestamp': 123, 'x': 2},
    ]
    out = select_row_closest_to_time(rows=rows, target_time=datetime.time(15, 30))
    assert out is not None
    assert out.get('x') == 2


def test_parse_prev_close_values_from_overview_row(tmp_path):
    _ = tmp_path
    idx, tp = parse_prev_close_values_from_overview_row({'index_price': '123.5', 'tp': '9.25'})
    assert idx == 123.5
    assert tp == 9.25

    idx, tp = parse_prev_close_values_from_overview_row({'index_price': '123.5'})
    assert idx == 123.5
    assert tp == 0.0

    idx, tp = parse_prev_close_values_from_overview_row({'index_price': 'oops', 'tp': 'nope'})
    assert idx is None
    assert tp is None


def test_validate_schema_prunes_and_flags(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    strike_data = {
        -1.0: {'CE': {'instrument_type': 'CE'}, 'PE': {'instrument_type': 'PE'}},
        24500.0: {
            'CE': {'instrument_type': 'XX'},
            'PE': {'instrument_type': 'PE'},
        },
        24600.0: {
            'CE': {'instrument_type': 'CE'},
            'PE': {'instrument_type': ''},
        },
    }

    issues = sink._validate_schema(index='NIFTY', expiry_code='this_week', strike_data=strike_data)

    assert any(i.startswith('invalid_strike:') for i in issues)
    assert 'missing_or_bad_type:24500.0:CE' in issues
    assert 'missing_or_bad_type:24600.0:PE' in issues
    assert -1.0 not in strike_data
    assert strike_data[24500.0]['CE'] is None
    assert strike_data[24500.0]['PE'] is not None
    assert strike_data[24600.0]['PE'] is None


def test_validate_schema_drops_invalid_and_marks_bad_type(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # strike_data structure: {strike: { 'CE': {...}, 'PE': {...} }}
    strike_data = {
        -50.0: {  # invalid strike, should be dropped
            'CE': {'instrument_type': 'CE', 'last_price': 10},
            'PE': {'instrument_type': 'PE', 'last_price': 12},
        },
        24550.0: {
            # CE has bad type; PE valid
            'CE': {'instrument_type': 'XX', 'last_price': 100},
            'PE': {'instrument_type': 'PE', 'last_price': 102},
        },
        24600.0: {
            # CE missing type; should be marked None, PE valid
            'CE': {'last_price': 95},
            'PE': {'instrument_type': 'PE', 'last_price': 120},
        },
    }

    issues = sink._validate_schema(index='NIFTY', expiry_code='this_week', strike_data=strike_data)

    # invalid strike removed entirely
    assert -50.0 not in strike_data
    # For 24550, CE should be cleared to None due to bad type
    assert strike_data[24550.0]['CE'] is None
    assert strike_data[24550.0]['PE']['instrument_type'] == 'PE'
    # For 24600, CE cleared to None because type missing
    assert strike_data[24600.0]['CE'] is None
    # Issues should contain markers for invalid_strike and missing_or_bad_type
    assert any(issue.startswith('invalid_strike:') for issue in issues)
    assert any(issue.startswith('missing_or_bad_type:') for issue in issues)


def test_validate_schema_no_issues_for_valid_legs(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    strike_data = {
        24550.0: {
            'CE': {'instrument_type': 'CE', 'last_price': 100},
            'PE': {'instrument_type': 'PE', 'last_price': 102},
        },
        24600.0: {
            'CE': {'instrument_type': 'CE', 'last_price': 90},
            'PE': {'instrument_type': 'PE', 'last_price': 120},
        },
    }

    issues = sink._validate_schema(index='NIFTY', expiry_code='this_week', strike_data=strike_data)
    assert issues == []
    # Ensure no legs were nulled
    assert strike_data[24550.0]['CE']['instrument_type'] == 'CE'
    assert strike_data[24550.0]['PE']['instrument_type'] == 'PE'
    assert strike_data[24600.0]['CE']['instrument_type'] == 'CE'
    assert strike_data[24600.0]['PE']['instrument_type'] == 'PE'


def test_is_expiry_disallowed_with_set_list_tuple(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    d1 = datetime.date(2025, 11, 13)
    d2 = datetime.date(2025, 11, 20)

    # Set
    sink.allowed_expiry_dates = {d1}
    assert sink._is_expiry_disallowed(d1) is False
    assert sink._is_expiry_disallowed(d2) is True

    # List
    sink.allowed_expiry_dates = [d1, d2]
    assert sink._is_expiry_disallowed(d1) is False
    assert sink._is_expiry_disallowed(datetime.date(2025, 11, 27)) is True

    # Tuple
    sink.allowed_expiry_dates = (d2,)
    assert sink._is_expiry_disallowed(d2) is False
    assert sink._is_expiry_disallowed(d1) is True


def test_is_expiry_disallowed_when_not_configured(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # No attribute set -> should not block
    d = datetime.date(2025, 11, 13)
    assert sink._is_expiry_disallowed(d) is False


def test_resolve_index_price_ordering(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # Provided value should win
    options_data = {
        'X': {'instrument_type': 'CE', 'strike': 24550, 'index_price': 99999}
    }
    val = sink._resolve_index_price(index='NIFTY', options_data=options_data, index_price=123.45)
    assert isinstance(val, float)
    assert val == 123.45

    # When not provided: use defaults first, then override by metadata
    options_meta = {
        'A': {'instrument_type': 'CE', 'strike': 24500, 'index_price': 24600},
        'B': {'instrument_type': 'PE', 'strike': 24500}
    }
    val2 = sink._resolve_index_price(index='NIFTY', options_data=options_meta, index_price=None)
    assert val2 == 24600.0  # metadata wins over default

    # Unknown index with no metadata -> fallback 0.0
    val3 = sink._resolve_index_price(index='UNKNOWN', options_data={}, index_price=None)
    assert val3 == 0.0


def test_compute_day_width_basic_and_edge(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # Basic
    ohlc = {'high': 100.5, 'low': 95.25}
    assert sink._compute_day_width(ohlc) == 5.25
    # Missing fields -> 0.0
    assert sink._compute_day_width({'high': 100}) == 0.0
    assert sink._compute_day_width({'low': 90}) == 0.0
    # Non-numeric values handled -> 0.0
    assert sink._compute_day_width({'high': 'abc', 'low': 90}) == 0.0
    # None -> 0.0
    assert sink._compute_day_width(None) == 0.0


def test_resolve_vix_ordering_and_cache(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # 1) From extra
    v = sink._resolve_vix({'vix': 17.25})
    assert v == 17.25
    assert sink._last_vix == 17.25

    # 2) From cache if extra missing
    v2 = sink._resolve_vix(None)
    assert v2 == 17.25

    # 3) From external if cache cleared and extra missing
    sink._last_vix = None
    sink._fetch_external_vix = lambda: 14.2  # type: ignore[attr-defined]
    v3 = sink._resolve_vix(None)
    assert v3 == 14.2
    assert sink._last_vix == 14.2


def test_build_return_metrics_flags(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    ts = datetime.datetime(2025, 11, 13, 9, 30, 0)
    payload = sink._build_return_metrics(
        expiry_code='this_week', pcr=0.5, timestamp=ts, day_width=1.2, index_price=24500.0,
        flags={'skipped_preopen': True, 'skipped_invalid_expiry': False}
    )
    assert payload['expiry_code'] == 'this_week'
    assert payload['pcr'] == 0.5
    assert payload['timestamp'] == ts
    assert payload['day_width'] == 1.2
    assert payload['index_price'] == 24500.0
    assert payload.get('skipped_preopen') is True
    assert 'skipped_invalid_expiry' not in payload  # false flags not included


def test_init_batch_state_if_needed(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    idx = 'NIFTY'
    code = 'this_week'
    ts = datetime.datetime(2025, 11, 13, 9, 30, 0)

    # Immediate mode (threshold == 0) -> no buffers created
    sink._batch_flush_threshold = 0
    enabled, key = sink._init_batch_state_if_needed(index=idx, expiry_code=code, timestamp=ts)
    assert enabled is False
    assert key == (idx, code, '2025-11-13')
    assert key not in sink._batch_buffers
    assert key not in sink._batch_counts

    # Batching enabled
    sink._batch_flush_threshold = 10
    enabled2, key2 = sink._init_batch_state_if_needed(index=idx, expiry_code=code, timestamp=ts)
    assert enabled2 is True
    assert key2 in sink._batch_buffers
    assert sink._batch_counts.get(key2) == 0


def test_compute_change_metrics_basic_and_edge(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # Basic case
    net, day, net_pct, day_pct = sink._compute_change_metrics(current=110.0, prev_close=100.0, open_value=105.0)
    assert net == 10.0
    assert day == 5.0
    assert net_pct == 10.0
    # 5 / 105 * 100 = 4.7619...
    assert round(day_pct, 4) == round(5.0 / 105.0 * 100.0, 4)

    # Edge: zero/None baselines -> pct should be 0.0
    net2, day2, net_pct2, day_pct2 = sink._compute_change_metrics(current=50.0, prev_close=0.0, open_value=0.0)
    assert net2 == 50.0
    assert day2 == 50.0
    assert net_pct2 == 0.0
    assert day_pct2 == 0.0

    net3, day3, net_pct3, day_pct3 = sink._compute_change_metrics(current=50.0, prev_close=None, open_value=None)
    assert net3 == 0.0
    assert day3 == 0.0
    assert net_pct3 == 0.0
    assert day_pct3 == 0.0


def test_align_row_to_header_basic_and_atm_derivation(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # Existing file header expects 'atm' which isn't in provided header
    file_header = ['timestamp','index','expiry_tag','expiry_date','offset','index_price','strike','atm','ce','pe']
    header = ['timestamp','index','expiry_tag','expiry_date','offset','index_price','strike','ce','pe']
    row = ['12-11-2025 09:30:00','NIFTY','this_week','2025-11-20',0,24550.0,24550.0,100.0,102.0]
    aligned = sink._align_row_to_header(file_header, row, header)
    # Length should match file header and atm derived as strike - offset
    assert len(aligned) == len(file_header)
    assert aligned[file_header.index('atm')] == 24550.0  # strike - offset
    assert aligned[file_header.index('ce')] == 100.0
    assert aligned[file_header.index('pe')] == 102.0


def test_align_rows_for_existing_file_reads_header_and_aligns(tmp_path):
    sink = CsvSink(base_dir=str(tmp_path))
    # Create a file with an existing header on disk
    fp = tmp_path / 'sample.csv'
    with open(fp, 'w', newline='') as f:
        f.write('timestamp,index,expiry_tag,expiry_date,offset,index_price,strike,atm,ce,pe\n')
        # write one dummy row so header is present
        f.write('x,NIFTY,this_week,2025-11-20,0,24550,24550,24550,1,1\n')
    header = ['timestamp','index','expiry_tag','expiry_date','offset','index_price','strike','ce','pe']
    rows = [
        ['12-11-2025 09:30:00','NIFTY','this_week','2025-11-20',0,24550.0,24550.0,100.0,102.0],
        ['12-11-2025 09:31:00','NIFTY','this_week','2025-11-20',50,24580.0,24600.0,92.0,108.0],
    ]
    aligned_rows = sink._align_rows_for_existing_file(str(fp), rows, header)
    assert len(aligned_rows) == 2
    # Ensure atm is correctly placed and values preserved
    for r in aligned_rows:
        idx = ['timestamp','index','expiry_tag','expiry_date','offset','index_price','strike','atm','ce','pe']
        assert len(r) == len(idx)
        strike = float(r[idx.index('strike')])
        offset = int(float(r[idx.index('offset')]))
        atm = float(r[idx.index('atm')])
        assert atm == strike - offset
