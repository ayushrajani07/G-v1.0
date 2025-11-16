"""Pruning facades extracted from metrics.py.

Provides public helpers for dynamic metric group pruning and preview.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "prune_metrics_groups",
    "preview_prune_metrics_groups",
]


def _get_registry():  # lazy import to avoid cycles
    try:
        from .metrics import get_metrics_singleton  # type: ignore
        return get_metrics_singleton()
    except (ImportError, AttributeError, TypeError, RuntimeError):
        # Handle missing module, attribute access, type issues, or initialization failures
        return None


def prune_metrics_groups(reload_filters: bool = True, *, dry_run: bool = False) -> dict[str, Any]:  # pragma: no cover - thin facade
    reg = _get_registry()
    if reg is None:
        return {}
    try:
        return reg.prune_groups(reload_filters=reload_filters, dry_run=dry_run)  # type: ignore[attr-defined]
    except (AttributeError, TypeError, RuntimeError) as e:  # pragma: no cover
        # Handle missing method, type issues, or pruning operation failures
        logger.debug("prune_metrics_groups failed: %s", e)
        return {}


def preview_prune_metrics_groups(reload_filters: bool = True) -> dict[str, Any]:  # pragma: no cover - thin facade
    try:
        return prune_metrics_groups(reload_filters=reload_filters, dry_run=True)
    except (AttributeError, TypeError, RuntimeError):
        # Handle method call failures
        return {}
