"""Greek metrics extraction module.

Provides a function to initialize greek-related option metrics formerly
implemented inside `MetricsRegistry._init_greek_metrics` without changing
metric names, labels or grouping semantics.
"""
from collections.abc import Sequence

from prometheus_client import Gauge, REGISTRY


def init_greek_metrics(registry, greek_names: Sequence[str] = ('delta','theta','gamma','vega','rho','iv')) -> None:
    """Attach greek option metrics to the provided registry instance.

    Parameters
    ----------
    registry : MetricsRegistry-like
        Instance expected to expose `_metric_groups` dict for grouping bookkeeping.
    greek_names : sequence of str
        Iterable of greek metric suffixes to register (default canonical set).
    """
    core = getattr(registry, '_core_reg', None)
    for greek in greek_names:
        metric_attr = f"option_{greek}"
        prom_name = f"g6_option_{greek}"
        if hasattr(registry, metric_attr):  # idempotent guard
            continue
        if callable(core):
            # Prefer centralized duplicate-safe registration.
            core(metric_attr, Gauge, prom_name, f'Option {greek}', ['index', 'expiry', 'strike', 'type'], group='greeks')
            continue
        # Fallback (older registry): tolerate duplicates via global REGISTRY lookup.
        g = None
        try:
            g = Gauge(prom_name, f'Option {greek}', ['index', 'expiry', 'strike', 'type'])
        except ValueError:
            try:
                names_map = getattr(REGISTRY, '_names_to_collectors', {})
                g = names_map.get(prom_name)
            except (AttributeError, TypeError):
                g = None
        if g is not None:
            try:
                setattr(registry, metric_attr, g)
            except (AttributeError, TypeError):
                pass
        try:
            registry._metric_groups[metric_attr] = 'greeks'
        except (AttributeError, TypeError, KeyError):
            # Handle missing attribute, type issues, or dict access failures
            pass
