"""Thin facade mirroring a subset of legacy provider functions.

For Patch 1 the facade delegates to the legacy `KiteProvider` where
appropriate to avoid behaviour changes. As components are migrated,
this layer will switch to using `ProviderCore` subcomponents directly.
"""
from __future__ import annotations

import logging
import os
from typing import Any
import datetime as _dt

from src.config.env_config import EnvConfig
from src.provider.config import get_provider_config

from .core import ProviderCore

# Lazy import holder
KiteProvider = None  # type: ignore

logger = logging.getLogger(__name__)

_PROVIDER_CORE: ProviderCore | None = None
_LEGACY_SINGLETON = None  # legacy KiteProvider instance (lazy)
LEGACY_IMPORT = "src.broker.kite_provider"

# Optional gate (default enabled) in case early adopters want to disable.
_SKELETON_FLAG = not EnvConfig.get_bool("G6_PROVIDER_SKELETON", True)


def _ensure_core() -> ProviderCore:
    global _PROVIDER_CORE  # noqa: PLW0603
    if _PROVIDER_CORE is None:
        _PROVIDER_CORE = ProviderCore.build()
        logger.info("provider.skeleton.init enabled=%s", _SKELETON_FLAG)
    return _PROVIDER_CORE

# --- Public facade functions (delegating to legacy for now) ---------------

def _legacy_provider():
    global _LEGACY_SINGLETON  # noqa: PLW0603
    global KiteProvider  # noqa: PLW0603
    if _LEGACY_SINGLETON is None:
        # Attempt import lazily to survive early import ordering issues
        if KiteProvider is None:
            try:
                from src.broker.kite_provider import KiteProvider as _KP  # type: ignore
                KiteProvider = _KP  # type: ignore
            except Exception:  # pragma: no cover
                # Log once without stack to reduce noise; tests assert presence of this marker
                logger.error("legacy_provider_import_failed")
                return None
        snap = get_provider_config()
        _LEGACY_SINGLETON = KiteProvider.from_provider_config(snap)  # type: ignore[arg-type]
        logger.debug("provider.facade.legacy_singleton_init id=%s", id(_LEGACY_SINGLETON))
    return _LEGACY_SINGLETON


def get_instruments(exchange: str | None = None, force_refresh: bool = False):
    """Delegate to legacy provider instance for now.

    We import lazily to keep import side-effects minimal.
    """
    provider = _legacy_provider()
    if provider is None:
        return []
    return provider.get_instruments(exchange=exchange or "NFO", force_refresh=force_refresh)

def get_expiry_dates(index_symbol: str):
    provider = _legacy_provider()
    if provider is None:
        return []
    return provider.get_expiry_dates(index_symbol)

def get_weekly_expiries(index_symbol: str):
    exp = get_expiry_dates(index_symbol)
    return exp[:2]

def get_monthly_expiries(index_symbol: str):
    exp = get_expiry_dates(index_symbol)
    # simple month grouping replicating legacy pattern (best-effort on small set)
    by_month: dict[tuple[int, int], list[Any]] = {}
    for d in exp:
        key = (getattr(d, 'year', None), getattr(d, 'month', None))
        if None not in key:
            # mypy/pylance friendliness: cast tuple once validated
            key_t = (int(d.year), int(d.month))  # type: ignore[arg-type]
            by_month.setdefault(key_t, []).append(d)
    out: list[Any] = []
    for _, vals in sorted(by_month.items()):
        out.append(max(vals))
    return out

def resolve_expiry(index_symbol: str, rule: str):
    provider = _legacy_provider()
    if provider is None:
        return _dt.date.today()
    return provider.resolve_expiry(index_symbol, rule)

def provider_diagnostics():
    provider = _legacy_provider()
    if provider is None:
        return {}
    return provider.provider_diagnostics()


def _debug_legacy_provider_id() -> int | None:
    p = _legacy_provider()
    return id(p) if p else None

__all__ = [
    "get_instruments",
    "get_expiry_dates",
    "get_weekly_expiries",
    "get_monthly_expiries",
    "resolve_expiry",
    "provider_diagnostics",
    "_debug_legacy_provider_id",
]
