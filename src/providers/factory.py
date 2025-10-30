#!/usr/bin/env python3
"""
Provider factory for the G6 platform.

Creates concrete provider implementations based on simple type identifiers.
Backwards compatible: reuses existing broker.kite_provider classes.
"""
from __future__ import annotations

from typing import Any
import warnings

# Optional imports - may fail if modules unavailable
try:
    from src.broker.provider_registry import get_provider  # type: ignore
except ImportError:
    get_provider = None  # type: ignore

try:
    from src.broker.kite_provider import (
        kite_provider_factory,
        DEPRECATION_MSG_FACTORY_IMPLICIT,
        DummyKiteProvider,
    )
except ImportError:
    kite_provider_factory = None  # type: ignore
    DEPRECATION_MSG_FACTORY_IMPLICIT = ""
    DummyKiteProvider = None  # type: ignore


def create_provider(provider_type: str, config: dict[str, Any] | None = None):
    """Create a provider instance.

    Enhancements (A7 Step 11 shim):
      - If provider_type is empty / 'auto', attempt to resolve via provider_registry
        (`G6_PROVIDER` env or default). Falls back to legacy kite path if registry
        unavailable or returns None.
    """
    ptype = (provider_type or "").lower()
    cfg = config or {}
    if ptype in ('', 'auto'):
        try:
            inst = get_provider() if get_provider is not None else None
            if inst is not None:
                return inst
        except Exception:
            pass  # silent fallback to legacy behavior
    if ptype in ("kite", "zerodha", "kiteconnect"):
        if kite_provider_factory is None:
            raise ImportError("kite_provider_factory not available")
        api_key = cfg.get("api_key")
        access_token = cfg.get("access_token")
        if api_key or access_token:
            # Apply overrides via factory (suppresses constructor deprecation warning)
            return kite_provider_factory(api_key=api_key, access_token=access_token)
        # Preserve legacy test expectation: constructing a kite provider via factory
        # with implicit env credentials emits a deprecation warning (migration notice).
        warnings.warn(DEPRECATION_MSG_FACTORY_IMPLICIT, DeprecationWarning, stacklevel=2)
        return kite_provider_factory()
    if ptype in ("dummy", "mock"):
        if DummyKiteProvider is None:
            raise ImportError("DummyKiteProvider not available")
        return DummyKiteProvider()
    raise ValueError(f"Unsupported provider type: {provider_type}")


__all__ = ["create_provider"]
