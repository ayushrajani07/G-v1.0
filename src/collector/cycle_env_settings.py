#!/usr/bin/env python3
"""Per-cycle environment-derived settings snapshot.

Captures frequently read G6_* flags/values once and exposes typed attributes.
This avoids repeated os.environ lookups scattered across the hot path and keeps
behavior centralized. It complements CollectorSettings (longer-lived knobs) by
focusing on per-cycle presentation/behavior flags (banners, output style,
stale/outage gating).
"""
from __future__ import annotations

from dataclasses import dataclass
import os

__all__ = ["CycleEnvSettings"]


def _truthy(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _as_int(val: str | None, default: int) -> int:
    try:
        return int(val) if val is not None and val != "" else default
    except Exception:
        return default


def _norm_lower(val: str | None, default: str) -> str:
    try:
        v = (val if val is not None and val != "" else default)
        return str(v).strip().lower()
    except Exception:
        return default


@dataclass(slots=True)
class CycleEnvSettings:
    # Presentation / logging
    refactor_debug: bool
    single_header_mode: bool
    banner_debug: bool
    daily_header_every_cycle: bool
    disable_repeat_banners: bool
    compact_banners: bool

    # Data quality / feature toggles
    enable_data_quality: bool

    # Cycle output formatting
    disable_pretty_cycle: bool
    cycle_output: str  # pretty | raw | both
    cycle_style: str   # legacy | readable

    # Stale system control
    stale_write_mode: str  # mark | abort
    stale_abort_cycles: int

    # Provider outage classification
    provider_outage_threshold: int
    provider_outage_log_every: int

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, *, collector_settings: object | None = None) -> "CycleEnvSettings":
        e = env if env is not None else os.environ
        # Prefer values from collector_settings when provided, else fallback to env
        pot = None
        pole = None
        if collector_settings is not None:
            try:
                pot = int(getattr(collector_settings, "provider_outage_threshold", None))  # type: ignore[arg-type]
            except Exception:
                pot = None
            try:
                pole = int(getattr(collector_settings, "provider_outage_log_every", None))  # type: ignore[arg-type]
            except Exception:
                pole = None
        return cls(
            refactor_debug=_truthy(e.get("G6_COLLECTOR_REFACTOR_DEBUG"), False),
            single_header_mode=_truthy(e.get("G6_SINGLE_HEADER_MODE"), False),
            banner_debug=_truthy(e.get("G6_BANNER_DEBUG"), False),
            daily_header_every_cycle=_truthy(e.get("G6_DAILY_HEADER_EVERY_CYCLE"), False),
            disable_repeat_banners=_truthy(e.get("G6_DISABLE_REPEAT_BANNERS"), False),
            compact_banners=_truthy(e.get("G6_COMPACT_BANNERS"), False),
            enable_data_quality=_truthy(e.get("G6_ENABLE_DATA_QUALITY"), False),
            disable_pretty_cycle=_truthy(e.get("G6_DISABLE_PRETTY_CYCLE"), False),
            cycle_output=_norm_lower(e.get("G6_CYCLE_OUTPUT"), "pretty"),
            cycle_style=_norm_lower(e.get("G6_CYCLE_STYLE"), "legacy"),
            stale_write_mode=_norm_lower(e.get("G6_STALE_WRITE_MODE"), "mark"),
            stale_abort_cycles=_as_int(e.get("G6_STALE_ABORT_CYCLES"), 10),
            provider_outage_threshold=int(pot) if isinstance(pot, int) and pot > 0 else _as_int(e.get("G6_PROVIDER_OUTAGE_THRESHOLD"), 3),
            provider_outage_log_every=int(pole) if isinstance(pole, int) and pole > 0 else _as_int(e.get("G6_PROVIDER_OUTAGE_LOG_EVERY"), 5),
        )
