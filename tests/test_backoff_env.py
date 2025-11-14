import os
import random
import pytest

from src.utils.backoff import backoff_delays, load_backoff_config, iter_backoff_from_env


def test_backoff_default_no_env(monkeypatch):
    # Ensure no env leakage
    for k in ("G6_BACKOFF_MAX_RETRIES","G6_BACKOFF_BASE_MS","G6_BACKOFF_FACTOR","G6_BACKOFF_CAP_MS","G6_BACKOFF_JITTER_MS"):
        monkeypatch.delenv(k, raising=False)
    cfg = load_backoff_config()
    assert cfg.max_retries == 0
    seq = list(backoff_delays(max_retries=3, base_ms=100.0, factor=2.0, cap_ms=500.0))
    assert seq == [100.0, 200.0, 400.0]


def test_backoff_env_overrides_simple(monkeypatch):
    monkeypatch.setenv("G6_BACKOFF_MAX_RETRIES","3")
    monkeypatch.setenv("G6_BACKOFF_BASE_MS","50")
    monkeypatch.setenv("G6_BACKOFF_FACTOR","2.0")
    monkeypatch.setenv("G6_BACKOFF_CAP_MS","180")
    cfg = load_backoff_config()
    assert cfg.max_retries == 3
    assert cfg.base_ms == 50.0 and cfg.factor == 2.0 and cfg.cap_ms == 180.0
    seq = list(iter_backoff_from_env())
    # 50, 100, 180 (capped from 200)
    assert seq == [50.0, 100.0, 180.0]


def test_backoff_env_jitter_range(monkeypatch):
    monkeypatch.setenv("G6_BACKOFF_MAX_RETRIES","3")
    monkeypatch.setenv("G6_BACKOFF_BASE_MS","10")
    monkeypatch.setenv("G6_BACKOFF_FACTOR","2.0")
    monkeypatch.setenv("G6_BACKOFF_CAP_MS","1000")
    # Jitter as range
    monkeypatch.setenv("G6_BACKOFF_JITTER_MS","1,1")
    random.seed(123)
    seq = list(iter_backoff_from_env())
    # With fixed jitter (1,1) each step +1
    assert seq == [11.0, 21.0, 41.0]


def test_backoff_env_jitter_scalar(monkeypatch):
    monkeypatch.setenv("G6_BACKOFF_MAX_RETRIES","2")
    monkeypatch.setenv("G6_BACKOFF_BASE_MS","10")
    monkeypatch.setenv("G6_BACKOFF_FACTOR","2.0")
    monkeypatch.setenv("G6_BACKOFF_CAP_MS","1000")
    # Jitter scalar -> uniform[0,2]
    monkeypatch.setenv("G6_BACKOFF_JITTER_MS","2")
    random.seed(1)
    seq = list(iter_backoff_from_env())
    assert len(seq) == 2
    # Deterministic approximate bounds
    assert 10.0 <= seq[0] <= 12.0
    assert 20.0 <= seq[1] <= 22.0
