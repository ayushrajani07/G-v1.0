"""Greek metrics extraction module.

Provides a function to initialize greek-related option metrics formerly
implemented inside `MetricsRegistry._init_greek_metrics` without changing
metric names, labels or grouping semantics.
"""
from collections.abc import Sequence

from prometheus_client import Gauge


def init_greek_metrics(registry, greek_names: Sequence[str] = ('delta','theta','gamma','vega','rho','iv')) -> None:
    """Attach greek option metrics to the provided registry instance.

    Parameters
    ----------
    registry : MetricsRegistry-like
        Instance expected to expose `_metric_groups` dict for grouping bookkeeping.
    greek_names : sequence of str
        Iterable of greek metric suffixes to register (default canonical set).
    """
    for greek in greek_names:
        metric_name = f"option_{greek}"
        if hasattr(registry, metric_name):  # idempotent guard
            continue
        prom_name = f'g6_option_{greek}'
        # Check if already registered in Prometheus to avoid duplicates
        try:
            from prometheus_client import REGISTRY
            existing = [c for c in REGISTRY._collector_to_names if prom_name in REGISTRY._collector_to_names.get(c, [])]
            if existing:
                # Already registered, reuse existing metric
                setattr(registry, metric_name, existing[0])
                continue
        except (ImportError, AttributeError, KeyError):
            pass
        g = Gauge(
            prom_name,
            f'Option {greek}',
            ['index', 'expiry', 'strike', 'type']
        )
        setattr(registry, metric_name, g)
        try:
            registry._metric_groups[metric_name] = 'greeks'
        except (AttributeError, TypeError, KeyError):
            # Handle missing attribute, type issues, or dict access failures
            pass
