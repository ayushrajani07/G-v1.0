from __future__ import annotations

import random
import time
from typing import Generator, Optional
from dataclasses import dataclass

try:
    from src.config.env_config import EnvConfig  # type: ignore
except Exception:  # pragma: no cover - fallback shim
    class EnvConfig:  # type: ignore
        @staticmethod
        def get_float(name: str, default: float) -> float:
            import os
            try:
                return float(os.environ.get(name, default))
            except Exception:
                return default
        @staticmethod
        def get_int(name: str, default: int) -> int:
            import os
            try:
                return int(float(os.environ.get(name, default)))
            except Exception:
                return default
        @staticmethod
        def get_str(name: str, default: str = "") -> str:
            import os
            return os.environ.get(name, default)

__all__ = [
    "backoff_delays",
    "sleep_ms",
    "BackoffConfig",
    "load_backoff_config",
    "iter_backoff_from_env",
]


@dataclass(frozen=True)
class BackoffConfig:
    max_retries: int
    base_ms: float = 100.0
    factor: float = 1.3
    cap_ms: float = 2000.0
    jitter_ms: float | tuple[float, float] | None = None

    @staticmethod
    def from_env(prefix: str = "G6_BACKOFF_") -> "BackoffConfig":
        """Load backoff configuration from environment.

        Recognized variables (prefix=G6_BACKOFF_ by default):
          - {prefix}MAX_RETRIES (int)
          - {prefix}BASE_MS (float)
          - {prefix}FACTOR (float)
          - {prefix}CAP_MS (float)
          - {prefix}JITTER_MS (float or "low,high")
        """
        mr = max(0, EnvConfig.get_int(prefix + "MAX_RETRIES", 0))
        base = EnvConfig.get_float(prefix + "BASE_MS", 100.0)
        fac = EnvConfig.get_float(prefix + "FACTOR", 1.3)
        cap = EnvConfig.get_float(prefix + "CAP_MS", 2000.0)
        raw_j = EnvConfig.get_str(prefix + "JITTER_MS", "").strip()
        jit: float | tuple[float, float] | None
        if raw_j:
            if "," in raw_j:
                try:
                    lo, hi = raw_j.split(",", 1)
                    jit = (float(lo), float(hi))
                except Exception:
                    jit = None
            else:
                try:
                    jit = float(raw_j)
                except Exception:
                    jit = None
        else:
            jit = None
        return BackoffConfig(max_retries=mr, base_ms=base, factor=fac, cap_ms=cap, jitter_ms=jit)


def backoff_delays(
    *,
    max_retries: int,
    base_ms: float = 100.0,
    factor: float = 1.3,
    cap_ms: float = 2000.0,
    jitter_ms: float | tuple[float, float] | None = None,
) -> Generator[float, None, None]:
    """Yield backoff delays in milliseconds for a finite number of retries.

    Parameters
    - max_retries: total retry attempts allowed (0 means no retries)
    - base_ms: initial delay in ms
    - factor: multiplicative growth per attempt
    - cap_ms: upper bound on delay
    - jitter_ms: optional jitter to add to each delay. If a tuple (low, high)
                 is provided, a random uniform jitter in that range is applied.
                 If a float is provided, a random uniform in [0, jitter_ms] is applied.
    """
    delay = float(base_ms)
    for _ in range(max(0, int(max_retries))):
        d = min(delay, float(cap_ms))
        if jitter_ms is not None:
            if isinstance(jitter_ms, tuple):
                lo, hi = jitter_ms
                d += random.uniform(float(lo), float(hi))
            else:
                d += random.uniform(0.0, float(jitter_ms))
        yield d
        delay = delay * float(factor)


def sleep_ms(ms: float, *, _sleep=time.sleep) -> None:
    """Sleep for the specified milliseconds. Broken out for testability."""
    if ms <= 0:
        return
    _sleep(ms / 1000.0)


def load_backoff_config(prefix: str = "G6_BACKOFF_") -> BackoffConfig:
    """Public helper to load BackoffConfig from environment (test-friendly)."""
    return BackoffConfig.from_env(prefix=prefix)


def iter_backoff_from_env(*, max_retries: int | None = None, prefix: str = "G6_BACKOFF_") -> Generator[float, None, None]:
    """Yield backoff delays using environment configuration.

    If max_retries is provided, it overrides the env-derived value.
    """
    cfg = BackoffConfig.from_env(prefix=prefix)
    mr = cfg.max_retries if max_retries is None else max_retries
    yield from backoff_delays(
        max_retries=mr,
        base_ms=cfg.base_ms,
        factor=cfg.factor,
        cap_ms=cfg.cap_ms,
        jitter_ms=cfg.jitter_ms,
    )
