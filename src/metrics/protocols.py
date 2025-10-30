"""Typed protocols for Prometheus-like metrics and registry helpers.

These lightweight Protocols let us annotate metrics without importing
prometheus_client at analysis time. They cover the small subset of methods
we actually use across the codebase.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CounterLike(Protocol):
    def inc(self, amount: float | int = 1) -> None: ...
    def labels(self, *args: Any, **kwargs: str) -> CounterLike: ...


@runtime_checkable
class GaugeLike(Protocol):
    def set(self, value: float | int) -> None: ...
    def inc(self, amount: float | int = 1) -> None: ...
    def labels(self, *args: Any, **kwargs: str) -> GaugeLike: ...


@runtime_checkable
class HistogramLike(Protocol):
    def observe(self, value: float | int) -> None: ...
    def labels(self, *args: Any, **kwargs: str) -> HistogramLike: ...


__all__ = [
    "CounterLike",
    "GaugeLike",
    "HistogramLike",
]
