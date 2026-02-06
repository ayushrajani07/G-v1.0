"""Unified environment-derived configuration (Phase 5 scaffold).

This module introduces a single `G6Config` class that centralizes environment
variable parsing in one place.

Design goals:
- Parsing lives in `G6Config.__init__` (per roadmap).
- Values are effectively startup-only in production (EnvConfig caches) so we
  support a `refresh` flag via `get_g6_config(refresh=True)` for tests/tools.
- Keep the surface small initially (loop + metrics + a few bootstrap toggles).

This does not replace JSON config loading (`src.config.loader`) yet; it is a
parallel track used to consolidate env parsing and enable gradual call-site
migration.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config.env_config import EnvConfig

__all__ = [
    "G6Config",
    "get_g6_config",
]


def _parse_optional_positive_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        v = int(s)
    except Exception:
        return None
    return v if v > 0 else None


@dataclass(frozen=True, slots=True, init=False)
class G6Config:
    """Single env-derived config snapshot."""

    # Loop
    loop_interval_seconds: float
    loop_max_cycles: int | None

    # Metrics
    metrics_enabled: bool
    metrics_host: str
    metrics_port: int

    # Bootstrap toggles
    disable_components: bool
    catalog_http_enabled: bool

    def __init__(self) -> None:
        # Loop
        loop_interval = EnvConfig.get_float("G6_LOOP_INTERVAL_SECONDS", 30.0)
        max_cycles_raw = EnvConfig.get_str("G6_LOOP_MAX_CYCLES", "") or EnvConfig.get_str("G6_MAX_CYCLES", "")
        max_cycles = _parse_optional_positive_int(max_cycles_raw)

        # Metrics enable semantics:
        # - If G6_METRICS_ENABLED is set (non-empty), it wins.
        # - Else, if legacy G6_METRICS_ENABLE is set, use it.
        # - Else default True.
        enabled_raw_1 = EnvConfig.get_str("G6_METRICS_ENABLED", "")
        enabled_raw_2 = EnvConfig.get_str("G6_METRICS_ENABLE", "")
        if enabled_raw_1:
            metrics_enabled = EnvConfig.get_bool("G6_METRICS_ENABLED", False)
        elif enabled_raw_2:
            metrics_enabled = EnvConfig.get_bool("G6_METRICS_ENABLE", False)
        else:
            metrics_enabled = True
        metrics_host = EnvConfig.get_str("G6_METRICS_HOST", "0.0.0.0")
        metrics_port = EnvConfig.get_int("G6_METRICS_PORT", 9108)

        # Bootstrap
        disable_components = EnvConfig.get_bool("G6_DISABLE_COMPONENTS", False)
        catalog_http_enabled = EnvConfig.get_bool("G6_CATALOG_HTTP", False)

        object.__setattr__(self, "loop_interval_seconds", float(loop_interval))
        object.__setattr__(self, "loop_max_cycles", max_cycles)
        object.__setattr__(self, "metrics_enabled", bool(metrics_enabled))
        object.__setattr__(self, "metrics_host", str(metrics_host))
        object.__setattr__(self, "metrics_port", int(metrics_port))
        object.__setattr__(self, "disable_components", bool(disable_components))
        object.__setattr__(self, "catalog_http_enabled", bool(catalog_http_enabled))

    # Convenience compatibility aliases used by some transitional call sites
    @property
    def loop_interval(self) -> float:
        return self.loop_interval_seconds


_singleton: G6Config | None = None


def get_g6_config(*, refresh: bool = False) -> G6Config:
    """Return the process-wide singleton G6Config.

    Parameters
    ----------
    refresh:
        When True, clears EnvConfig cache and rebuilds the singleton.
        Primarily used by tests and CLI tooling.
    """
    global _singleton
    if _singleton is None or refresh:
        try:
            EnvConfig.clear_cache()
        except Exception:
            pass
        _singleton = G6Config()
    return _singleton
