#!/usr/bin/env python3
"""Print a concise metrics registry summary for local diagnostics.

Outputs:
- families: number of Prometheus metric families currently registered
- always_on_groups: from src.metrics.metrics (if available)
- enabled_raw/disabled_raw: environment values
- effective_enabled_count: how many groups are effectively enabled by gating
- groups_active: sorted list of active grouped metrics (by group label)
"""
from __future__ import annotations

import os
import sys
from typing import Any

try:
    from prometheus_client import REGISTRY  # type: ignore
except Exception:
    REGISTRY = None  # type: ignore

ROOT_ADDED = False
try:
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
        ROOT_ADDED = True
except Exception:
    pass


def main() -> int:
    try:
        import importlib
        metrics_pkg = importlib.import_module('src.metrics')
        reg = metrics_pkg.get_metrics_singleton()
        if reg is None:
            print("metrics: registry not initialized")
            return 1
    except Exception as e:
        print(f"metrics: failed to import/initialize: {e}")
        return 1

    # Families count
    families = -1
    try:
        if REGISTRY is not None:
            families = len(list(REGISTRY.collect()))
    except Exception:
        pass

    # Always-on groups length (best-effort)
    always_on_len = None
    try:
        metrics_mod = sys.modules.get('src.metrics.metrics')
        if metrics_mod is None:
            metrics_mod = __import__('src.metrics.metrics', fromlist=['*'])
        aog = getattr(metrics_mod, 'ALWAYS_ON_GROUPS', set())
        always_on_len = len(aog) if isinstance(aog, (set, list, tuple)) else None
    except Exception:
        pass

    # Env raw gating values
    enabled_raw = os.environ.get('G6_ENABLE_METRIC_GROUPS', '')
    disabled_raw = os.environ.get('G6_DISABLE_METRIC_GROUPS', '')

    # Effective enabled count (from registry state attached by gating)
    eff_count = None
    try:
        eff = getattr(reg, '_effective_enabled_groups', None)
        if isinstance(eff, set):
            eff_count = len(eff)
    except Exception:
        pass

    # Group activity (from metric_group_state gauge mapping)
    groups_active: list[str] = []
    try:
        groups_map: dict[str, str] = getattr(reg, '_metric_groups', {})  # attr->group
        groups_active = sorted(set(groups_map.values()))
    except Exception:
        pass

    print("metrics.info:")
    print(f"  families={families}")
    print(f"  always_on_groups={always_on_len}")
    print(f"  enabled_raw='{enabled_raw}' disabled_raw='{disabled_raw}'")
    print(f"  effective_enabled_count={eff_count}")
    print(f"  groups_active={groups_active}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
