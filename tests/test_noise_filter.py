"""Focused tests for the private _NoiseFilter in src.metrics.metrics.

These remain here with a deep import since _NoiseFilter is an internal helper
and not part of the stable facade surface. Keeping them isolated prevents
private API spillover into broader metrics tests.
"""

import logging
import pytest

from src.metrics.metrics import _NoiseFilter  # deep import intentional


def test_noise_filter_creation():
    f = _NoiseFilter()
    assert f is not None
    assert hasattr(f, 'filter')


def test_noise_filter_suppresses_repeats():
    f = _NoiseFilter()
    rec = logging.LogRecord(
        name='t', level=logging.INFO, pathname='x.py', lineno=1,
        msg='Prometheus default registry cleared via reset flag', args=(), exc_info=None
    )
    rec.message = rec.msg
    first = f.filter(rec)
    second = f.filter(rec)
    assert first is True and second is False


def test_noise_filter_allows_critical():
    f = _NoiseFilter()
    rec = logging.LogRecord(
        name='t', level=logging.ERROR, pathname='x.py', lineno=1,
        msg='Error message', args=(), exc_info=None
    )
    rec.message = rec.msg
    assert f.filter(rec) is True


def test_noise_filter_preserves_structured_events():
    f = _NoiseFilter()
    rec = logging.LogRecord(
        name='t', level=logging.INFO, pathname='x.py', lineno=1,
        msg='metrics.group_filters.loaded', args=(), exc_info=None
    )
    rec.message = rec.msg
    assert f.filter(rec) is True


def test_noise_filter_allows_distinct_messages():
    f = _NoiseFilter()
    msgs = ['a', 'b', 'c']
    results = []
    for m in msgs:
        rec = logging.LogRecord('t', logging.INFO, 'x.py', 1, m, (), None)
        rec.message = m
        results.append(f.filter(rec))
    assert all(results)


def test_noise_filter_rejects_second_variant_same_message():
    f = _NoiseFilter()
    rec1 = logging.LogRecord('t', logging.INFO, 'x.py', 1, 'repeatable.msg', (), None)
    rec1.message = rec1.msg
    rec2 = logging.LogRecord('t', logging.INFO, 'x.py', 2, 'repeatable.msg', (), None)
    rec2.message = rec2.msg
    assert f.filter(rec1) is True
    assert f.filter(rec2) is False
