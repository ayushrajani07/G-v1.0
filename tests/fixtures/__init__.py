"""Shared test fixtures and utilities for G6 test suite.

This package centralizes common test utilities that were previously
duplicated across many test files. Import fixtures from submodules:

    from tests.fixtures.dummies import DummyProviders, DummyMetrics
    from tests.fixtures.factories import make_ctx, make_snapshot

Or import everything from the package:

    from tests.fixtures import DummyProviders, make_ctx, DummyMetrics
"""

from tests.fixtures.dummies import (
    DummyProviders,
    DummyMetrics,
    DummyCsvSink,
    DummyInfluxSink,
    DummySink,
    DummyGauge,
    DummyCounter,
    DummySummary,
    DummyLogger,
)

from tests.fixtures.factories import (
    make_ctx,
    make_snapshot,
    make_batcher,
    make_option,
    sample_quotes,
    sample_instruments,
)

__all__ = [
    # Dummies
    'DummyProviders',
    'DummyMetrics', 
    'DummyCsvSink',
    'DummyInfluxSink',
    'DummySink',
    'DummyGauge',
    'DummyCounter',
    'DummySummary',
    'DummyLogger',
    # Factories
    'make_ctx',
    'make_snapshot',
    'make_batcher',
    'make_option',
    'sample_quotes',
    'sample_instruments',
]
