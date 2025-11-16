"""SLA health metrics extraction module.

Provides registration for cycle SLA breach metric previously defined in
`placeholders.py`. Pure refactor: metric name, documentation, group tag,
and ordering (early always-on phase) preserved.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from prometheus_client import REGISTRY, Counter

__all__ = ["init_sla_placeholders"]

logger = logging.getLogger(__name__)


def init_sla_placeholders(reg: Any, group_allowed: Callable[[str], bool]) -> None:
    """Register SLA placeholder metrics (currently just cycle_sla_breach).

    Idempotent & duplicate-safe; mirrors prior placeholder semantics.
    """
    try:
        if hasattr(reg, 'cycle_sla_breach'):
            return
        strict = False
        try:
            strict = os.getenv('G6_METRICS_STRICT_EXCEPTIONS','').lower() in {'1','true','yes','on'}
        except (AttributeError, TypeError):  # pragma: no cover - env parse resilience
            # Handle attribute access or type issues
            pass
        metric = None
        try:
            metric = Counter('g6_cycle_sla_breach_total', 'Cycle SLA breach occurrences')
        except ValueError:
            # Duplicate in global collector set; attempt retrieval (mirrors placeholder logic style)
            try:
                for coll, names in getattr(REGISTRY, '_collector_to_names', {}).items():  # type: ignore[attr-defined]
                    if 'g6_cycle_sla_breach_total' in names:
                        metric = coll
                        break
            except (AttributeError, TypeError):
                # Handle missing registry attribute or type issues
                pass
        except (TypeError, RuntimeError) as e:  # unexpected type or runtime errors
            logger.error("init_sla_placeholders failed creating cycle_sla_breach: %s", e, exc_info=True)
            if strict:
                raise
            return
        if metric is not None:
            reg.cycle_sla_breach = metric
            try:
                if group_allowed('sla_health'):
                    reg._metric_groups['cycle_sla_breach'] = 'sla_health'  # type: ignore[attr-defined]
                    if hasattr(reg, 'metric_group_state'):
                        try:
                            reg.metric_group_state.labels(group='sla_health').set(1)  # type: ignore[attr-defined]
                        except (AttributeError, TypeError, ValueError, RuntimeError):
                            # Handle missing method, type issues, invalid values, or metric operation failures
                            pass
            except (AttributeError, TypeError, KeyError, RuntimeError):  # pragma: no cover - bookkeeping only
                # Handle attribute access, type issues, dict operations, or predicate call failures
                pass
    except (AttributeError, TypeError, RuntimeError):  # pragma: no cover - defensive catch-all
        # Handle unexpected attribute, type, or runtime errors
        logger.debug("init_sla_placeholders unexpected failure", exc_info=True)
