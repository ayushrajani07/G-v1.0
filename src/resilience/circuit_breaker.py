"""Simple circuit breaker utility for outbound calls.

State machine:
- CLOSED: calls pass; failures counted.
- OPEN: calls short-circuited; after recovery_timeout transitions to HALF_OPEN.
- HALF_OPEN: limited test calls (half_open_max_calls); on first success -> CLOSED; on failure -> OPEN.

Intended usage:
    breaker = CircuitBreaker(name="provider", failure_threshold=5, recovery_timeout=30)
    result = breaker.call(lambda: external_op())
Expose metrics via .metrics() for aggregation.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Callable, Any, Dict

@dataclass
class BreakerMetrics:
    name: str
    state: str
    failure_count: int
    open_timestamp: float | None
    half_open_trial_count: int

class CircuitBreaker:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 30.0, half_open_max_calls: int = 1):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.state = self.CLOSED
        self.failure_count = 0
        self.open_timestamp: float | None = None
        self.half_open_trial_count = 0

    def _transition_open(self):
        self.state = self.OPEN
        self.open_timestamp = time.time()

    def _transition_half_open(self):
        self.state = self.HALF_OPEN
        self.half_open_trial_count = 0

    def _transition_closed(self):
        self.state = self.CLOSED
        self.failure_count = 0
        self.open_timestamp = None
        self.half_open_trial_count = 0

    def _maybe_recover(self):
        if self.state == self.OPEN and self.open_timestamp is not None:
            if (time.time() - self.open_timestamp) >= self.recovery_timeout:
                self._transition_half_open()

    def call(self, fn: Callable[[], Any]) -> Any:
        self._maybe_recover()
        if self.state == self.OPEN:
            raise RuntimeError(f"CircuitBreaker '{self.name}' open")
        if self.state == self.HALF_OPEN:
            if self.half_open_trial_count >= self.half_open_max_calls:
                raise RuntimeError(f"CircuitBreaker '{self.name}' half-open saturation")
            self.half_open_trial_count += 1
        try:
            result = fn()
        except Exception:
            self.failure_count += 1
            if self.state == self.HALF_OPEN:
                self._transition_open()
            elif self.failure_count >= self.failure_threshold:
                self._transition_open()
            raise
        else:
            if self.state == self.HALF_OPEN:
                self._transition_closed()
            return result

    def metrics(self) -> Dict[str, Any]:
        return BreakerMetrics(
            name=self.name,
            state=self.state,
            failure_count=self.failure_count,
            open_timestamp=self.open_timestamp,
            half_open_trial_count=self.half_open_trial_count,
        ).__dict__

# Global registry for exporting metrics if needed
_BREAKERS: Dict[str, CircuitBreaker] = {}

def get_breaker(name: str) -> CircuitBreaker:
    if name not in _BREAKERS:
        _BREAKERS[name] = CircuitBreaker(name=name)
    return _BREAKERS[name]
