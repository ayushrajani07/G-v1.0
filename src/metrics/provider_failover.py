"""Provider failover metric extraction module.

Moves the always-on provider_failover counter out of placeholders.py while preserving:
 - Metric name: g6_provider_failover_total
 - Attribute: provider_failover
 - Group tag: provider_failover
 - Ordering: still initialized early (immediately after SLA placeholders)
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from prometheus_client import REGISTRY, Counter

__all__ = ["init_provider_failover_placeholders"]

logger = logging.getLogger(__name__)


def init_provider_failover_placeholders(reg: Any, group_allowed: Callable[[str], bool]) -> None:
    """Register provider_failover placeholder metric if absent.

    Duplicate-safe and resilient; mirrors prior placeholder semantics.
    """
    try:
        if hasattr(reg, 'provider_failover'):
            return
        strict = False
        try:
            strict = os.getenv('G6_METRICS_STRICT_EXCEPTIONS','').lower() in {'1','true','yes','on'}
        except (AttributeError, TypeError):
            # Handle attribute or type errors in env parsing
            pass
        metric = None
        try:
            metric = Counter('g6_provider_failover_total', 'Provider failover events')
        except ValueError:
            try:
                for coll, names in getattr(REGISTRY, '_collector_to_names', {}).items():  # type: ignore[attr-defined]
                    if 'g6_provider_failover_total' in names:
                        metric = coll
                        break
            except (AttributeError, TypeError):
                # Handle missing registry attribute or type issues
                pass
        except (TypeError, RuntimeError) as e:
            logger.error("init_provider_failover_placeholders failed creating provider_failover: %s", e, exc_info=True)
            if strict:
                raise
            return
        if metric is not None:
            reg.provider_failover = metric
            try:
                if group_allowed('provider_failover'):
                    reg._metric_groups['provider_failover'] = 'provider_failover'  # type: ignore[attr-defined]
                    if hasattr(reg, 'metric_group_state'):
                        try:
                            reg.metric_group_state.labels(group='provider_failover').set(1)  # type: ignore[attr-defined]
                        except (AttributeError, TypeError, ValueError, RuntimeError):
                            # Handle missing method, type issues, invalid values, or metric operation failures
                            pass
            except (AttributeError, TypeError, KeyError, RuntimeError):
                # Handle missing attributes, type issues, dict operations, or predicate call failures
                pass
    except (AttributeError, TypeError, RuntimeError):
        # Handle unexpected attribute, type, or runtime errors
        logger.debug("init_provider_failover_placeholders unexpected failure", exc_info=True)
