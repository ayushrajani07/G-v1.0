"""Circuit breaker pattern for provider and index resilience.

Implements Phase 4 of the Cycle Performance Roadmap: circuit breakers to prevent
cascading failures and provide automatic quarantine/recovery for failing indices.

The circuit breaker tracks error rates and automatically opens (blocks requests) when
the error threshold is exceeded. After a cooldown period, it enters a half-open state
to test if the service has recovered.

States:
    CLOSED: Normal operation, requests pass through
    OPEN: Error threshold exceeded, requests blocked
    HALF_OPEN: Testing recovery, limited requests allowed

Environment Variables:
    G6_CIRCUIT_BREAKER_ENABLED: Enable circuit breakers (default 0)
    G6_CIRCUIT_BREAKER_ERROR_THRESHOLD: Error rate to trip (0.0-1.0, default 0.5)
    G6_CIRCUIT_BREAKER_WINDOW_SECONDS: Time window for rate calculation (default 300)
    G6_CIRCUIT_BREAKER_COOLDOWN_SECONDS: Time before half-open test (default 600)
    G6_CIRCUIT_BREAKER_HALF_OPEN_ATTEMPTS: Requests in half-open state (default 3)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = 'closed'
    OPEN = 'open'
    HALF_OPEN = 'half_open'


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    error_threshold: float = 0.5  # 50% error rate trips breaker
    window_seconds: float = 300.0  # 5 minute window
    cooldown_seconds: float = 600.0  # 10 minute cooldown
    half_open_attempts: int = 3  # Attempts in half-open state
    enabled: bool = False
    
    @classmethod
    def from_env(cls) -> CircuitBreakerConfig:
        """Load configuration from environment."""
        from src.config.env_config import EnvConfig
        
        return cls(
            enabled=EnvConfig.get_bool('G6_CIRCUIT_BREAKER_ENABLED', False),
            error_threshold=EnvConfig.get_float('G6_CIRCUIT_BREAKER_ERROR_THRESHOLD', 0.5),
            window_seconds=EnvConfig.get_float('G6_CIRCUIT_BREAKER_WINDOW_SECONDS', 300.0),
            cooldown_seconds=EnvConfig.get_float('G6_CIRCUIT_BREAKER_COOLDOWN_SECONDS', 600.0),
            half_open_attempts=EnvConfig.get_int('G6_CIRCUIT_BREAKER_HALF_OPEN_ATTEMPTS', 3),
        )


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open and blocks a request."""
    pass


class CircuitBreaker:
    """Circuit breaker for a single resource (index/symbol/endpoint).
    
    Tracks success/failure rates and automatically trips when error rate exceeds
    threshold. Provides automatic recovery testing after cooldown period.
    """
    
    def __init__(self, name: str, config: CircuitBreakerConfig):
        """Initialize circuit breaker.
        
        Args:
            name: Identifier for this breaker (e.g., 'NIFTY', 'get_quotes')
            config: Configuration
        """
        self.name = name
        self.config = config
        self._state = CircuitState.CLOSED
        self._lock = threading.Lock()
        
        # Track events in sliding window
        self._events: deque[tuple[float, bool]] = deque()  # (timestamp, success)
        
        # State transition tracking
        self._opened_at: float = 0.0
        self._half_open_attempts = 0
        self._half_open_successes = 0
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            # Auto-transition from OPEN to HALF_OPEN after cooldown
            if self._state == CircuitState.OPEN:
                if time.time() - self._opened_at >= self.config.cooldown_seconds:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_attempts = 0
                    self._half_open_successes = 0
                    logger.info("Circuit breaker '%s' entering HALF_OPEN state", self.name)
            
            return self._state
    
    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute function through circuit breaker.
        
        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
        
        Returns:
            Result from func
        
        Raises:
            CircuitBreakerError: If circuit is open
        """
        # Check if request allowed
        if not self.is_request_allowed():
            raise CircuitBreakerError(f"Circuit breaker '{self.name}' is OPEN")
        
        # Execute function and record result
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise
    
    def is_request_allowed(self) -> bool:
        """Check if request should be allowed through breaker."""
        state = self.state  # May trigger state transition
        
        if state == CircuitState.CLOSED:
            return True
        
        if state == CircuitState.OPEN:
            return False
        
        # HALF_OPEN: allow limited attempts
        with self._lock:
            return self._half_open_attempts < self.config.half_open_attempts
    
    def record_success(self) -> None:
        """Record a successful operation."""
        now = time.time()
        
        with self._lock:
            self._events.append((now, True))
            self._cleanup_old_events(now)
            
            # State transitions
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_attempts += 1
                self._half_open_successes += 1
                
                # If all half-open attempts succeed, close the circuit
                if self._half_open_successes >= self.config.half_open_attempts:
                    self._state = CircuitState.CLOSED
                    logger.info("Circuit breaker '%s' recovered to CLOSED state", self.name)
    
    def record_failure(self) -> None:
        """Record a failed operation."""
        now = time.time()
        
        with self._lock:
            self._events.append((now, False))
            self._cleanup_old_events(now)
            
            # State transitions
            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open immediately reopens circuit
                self._state = CircuitState.OPEN
                self._opened_at = now
                logger.warning("Circuit breaker '%s' reopened due to half-open failure", self.name)
                return
            
            # Check if error rate exceeds threshold
            error_rate = self._calculate_error_rate()
            if error_rate >= self.config.error_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = now
                logger.warning(
                    "Circuit breaker '%s' opened due to error rate %.2f%%",
                    self.name,
                    error_rate * 100
                )
    
    def _cleanup_old_events(self, now: float) -> None:
        """Remove events outside the sliding window."""
        cutoff = now - self.config.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
    
    def _calculate_error_rate(self) -> float:
        """Calculate current error rate in sliding window."""
        if not self._events:
            return 0.0
        
        total = len(self._events)
        failures = sum(1 for _, success in self._events if not success)
        
        return failures / total if total > 0 else 0.0
    
    def get_stats(self) -> dict[str, Any]:
        """Get current breaker statistics."""
        with self._lock:
            now = time.time()
            self._cleanup_old_events(now)
            
            total = len(self._events)
            failures = sum(1 for _, success in self._events if not success)
            error_rate = failures / total if total > 0 else 0.0
            
            return {
                'name': self.name,
                'state': self._state.value,
                'error_rate': error_rate,
                'total_requests': total,
                'failures': failures,
                'window_seconds': self.config.window_seconds,
                'cooldown_remaining': max(0.0, self.config.cooldown_seconds - (now - self._opened_at)) if self._state == CircuitState.OPEN else 0.0,
            }
    
    def reset(self) -> None:
        """Manually reset circuit breaker to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._events.clear()
            self._opened_at = 0.0
            logger.info("Circuit breaker '%s' manually reset", self.name)


class CircuitBreakerRegistry:
    """Registry of circuit breakers for different resources.
    
    Provides singleton access to circuit breakers per resource (index/symbol/endpoint).
    """
    
    def __init__(self, config: CircuitBreakerConfig | None = None):
        """Initialize registry.
        
        Args:
            config: Configuration to use for all breakers (loads from env if None)
        """
        self.config = config or CircuitBreakerConfig.from_env()
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()
    
    def get(self, name: str) -> CircuitBreaker:
        """Get or create circuit breaker for resource.
        
        Args:
            name: Resource identifier (e.g., 'NIFTY', 'BANKNIFTY')
        
        Returns:
            CircuitBreaker instance
        """
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, self.config)
            return self._breakers[name]
    
    def get_all_stats(self) -> list[dict[str, Any]]:
        """Get statistics for all breakers.
        
        Returns:
            List of stat dicts for each breaker
        """
        with self._lock:
            return [breaker.get_stats() for breaker in self._breakers.values()]
    
    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()


# Global singleton registry
_GLOBAL_REGISTRY: CircuitBreakerRegistry | None = None
_GLOBAL_LOCK = threading.Lock()


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """Get the global circuit breaker registry.
    
    Returns:
        CircuitBreakerRegistry singleton
    """
    global _GLOBAL_REGISTRY
    
    with _GLOBAL_LOCK:
        if _GLOBAL_REGISTRY is None:
            _GLOBAL_REGISTRY = CircuitBreakerRegistry()
        return _GLOBAL_REGISTRY


__all__ = [
    'CircuitBreaker',
    'CircuitBreakerRegistry',
    'CircuitBreakerConfig',
    'CircuitBreakerError',
    'CircuitState',
    'get_circuit_breaker_registry',
]
