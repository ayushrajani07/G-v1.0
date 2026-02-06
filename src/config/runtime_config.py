"""Runtime configuration consolidation (Phase 2 skeleton).

This module provides a minimal, typed snapshot of a few frequently accessed
runtime parameters derived from environment variables. It does NOT replace the
existing comprehensive `config.loader` logic yet; it co-exists to enable gradual
adoption of a unified pattern (`get_runtime_config()`).

Rationale:
- Many modules read a small subset of loop/metrics env vars directly.
- Centralizing them reduces scattered os.getenv calls and paves the way for
  a frozen config object passed through `RuntimeContext`.

Scope (initial): loop interval, max cycles, metrics enable/port/host.
Future: extend with validated groups & feature flags once stable.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.config.g6_config import get_g6_config

__all__ = [
    "LoopSettings",
    "MetricsSettings",
    "RuntimeConfig",
    "get_runtime_config",
]

@dataclass(frozen=True)
class LoopSettings:
    interval_seconds: float
    max_cycles: int | None

@dataclass(frozen=True)
class MetricsSettings:
    enabled: bool
    host: str
    port: int

@dataclass(frozen=True)
class RuntimeConfig:
    loop: LoopSettings
    metrics: MetricsSettings

_singleton: RuntimeConfig | None = None

def build_runtime_config() -> RuntimeConfig:
    # Delegate parsing to the unified G6Config.
    cfg = get_g6_config(refresh=False)
    loop_interval = cfg.loop_interval_seconds
    max_cycles = cfg.loop_max_cycles
    metrics_enabled = cfg.metrics_enabled
    metrics_host = cfg.metrics_host
    metrics_port = cfg.metrics_port
    return RuntimeConfig(
        loop=LoopSettings(interval_seconds=loop_interval, max_cycles=max_cycles),
        metrics=MetricsSettings(enabled=metrics_enabled, host=metrics_host, port=metrics_port),
    )

def get_runtime_config(refresh: bool = False) -> RuntimeConfig:
    global _singleton
    if _singleton is None or refresh:
        if refresh:
            # Ensure env cache invalidation happens via the unified config.
            try:
                get_g6_config(refresh=True)
            except Exception:
                pass
        _singleton = build_runtime_config()
    return _singleton
