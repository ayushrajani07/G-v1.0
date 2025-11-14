import types
import os
from src.collector.cycle_env_settings import CycleEnvSettings


def test_cycle_env_settings_basic_mapping(monkeypatch):
    monkeypatch.setenv('G6_COLLECTOR_REFACTOR_DEBUG', '1')
    monkeypatch.setenv('G6_SINGLE_HEADER_MODE', '1')
    monkeypatch.setenv('G6_BANNER_DEBUG', 'true')
    monkeypatch.setenv('G6_DAILY_HEADER_EVERY_CYCLE', 'yes')
    monkeypatch.setenv('G6_DISABLE_REPEAT_BANNERS', 'on')
    monkeypatch.setenv('G6_COMPACT_BANNERS', '0')
    monkeypatch.setenv('G6_ENABLE_DATA_QUALITY', '1')
    monkeypatch.setenv('G6_DISABLE_PRETTY_CYCLE', '0')
    monkeypatch.setenv('G6_CYCLE_OUTPUT', 'BoTh')
    monkeypatch.setenv('G6_CYCLE_STYLE', 'Readable')
    monkeypatch.setenv('G6_STALE_WRITE_MODE', 'ABORT')
    monkeypatch.setenv('G6_STALE_ABORT_CYCLES', '2')
    monkeypatch.setenv('G6_PROVIDER_OUTAGE_THRESHOLD', '9')
    monkeypatch.setenv('G6_PROVIDER_OUTAGE_LOG_EVERY', '7')

    s = CycleEnvSettings.from_env()
    assert s.refactor_debug is True
    assert s.single_header_mode is True
    assert s.banner_debug is True
    assert s.daily_header_every_cycle is True
    assert s.disable_repeat_banners is True
    assert s.compact_banners is False  # '0'
    assert s.enable_data_quality is True
    assert s.disable_pretty_cycle is False
    assert s.cycle_output == 'both'
    assert s.cycle_style == 'readable'
    assert s.stale_write_mode == 'abort'
    assert s.stale_abort_cycles == 2
    assert s.provider_outage_threshold == 9
    assert s.provider_outage_log_every == 7


def test_cycle_env_settings_prefers_collector_settings(monkeypatch):
    # Even if env sets threshold/log_every, explicit CollectorSettings should win
    monkeypatch.setenv('G6_PROVIDER_OUTAGE_THRESHOLD', '3')
    monkeypatch.setenv('G6_PROVIDER_OUTAGE_LOG_EVERY', '4')

    fake_settings = types.SimpleNamespace(provider_outage_threshold=11, provider_outage_log_every=13)
    s = CycleEnvSettings.from_env(collector_settings=fake_settings)
    assert s.provider_outage_threshold == 11
    assert s.provider_outage_log_every == 13


def test_cycle_env_settings_defaults(monkeypatch):
    # Clear relevant envs
    for k in list(os.environ.keys()):
        if k.startswith('G6_'):
            monkeypatch.delenv(k, raising=False)
    s = CycleEnvSettings.from_env()
    assert s.cycle_output == 'pretty'
    assert s.cycle_style == 'legacy'
    assert s.stale_write_mode == 'mark'
    assert s.stale_abort_cycles == 10
    assert s.provider_outage_threshold == 3
    assert s.provider_outage_log_every == 5
