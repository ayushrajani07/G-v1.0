#!/usr/bin/env python3
"""CI guard: Validate docs/metrics_spec.yaml matches runtime registry surface.

- Fails if any metric in the spec is not present in the runtime registry.
- Tolerates env-gated entries (e.g., g6_vol_surface_rows_expiry) unless explicitly enabled.

This script intentionally avoids pytest; it should run in a vanilla CI job.
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from typing import Set

try:
    import yaml  # type: ignore
except Exception as e:  # pragma: no cover
    print(f"ERROR: Missing dependency pyyaml: {e}")
    sys.exit(2)

try:
    from prometheus_client import REGISTRY  # type: ignore
except Exception as e:  # pragma: no cover
    print(f"ERROR: Missing dependency prometheus_client: {e}")
    sys.exit(2)

# Ensure project root on path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SPEC_PATH = ROOT / 'docs' / 'metrics_spec.yaml'


def collect_runtime_metric_names() -> Set[str]:
    names: Set[str] = set()
    try:
        for fam in REGISTRY.collect():  # type: ignore[attr-defined]
            if getattr(fam, 'name', '').startswith('g6_'):
                names.add(fam.name)
        internal = getattr(REGISTRY, '_names_to_collectors', {})
        for key in internal.keys():
            if isinstance(key, str) and key.startswith('g6_'):
                names.add(key)
    except Exception:
        pass
    return names


def main() -> int:
    if not SPEC_PATH.exists():
        print(f"ERROR: metrics spec file missing: {SPEC_PATH}")
        return 2

    # Import metrics to initialize registry
    try:
        import importlib
        m = importlib.import_module('src.metrics.metrics')  # noqa: F401
        # Force instantiation to ensure grouped metrics registered deterministically
        if hasattr(m, 'get_metrics_singleton'):
            m.get_metrics_singleton()
    except Exception as e:
        print(f"ERROR: Failed importing/initializing metrics: {e}")
        return 2

    try:
        spec_data = yaml.safe_load(SPEC_PATH.read_text(encoding='utf-8')) or []
        spec_names: Set[str] = {entry['name'] for entry in spec_data if 'name' in entry}
    except Exception as e:
        print(f"ERROR: Failed reading spec: {e}")
        return 2

    runtime_names = collect_runtime_metric_names()

    # Treat env-gated per-expiry vol surface metrics as optional unless flag enabled
    flag = os.getenv('G6_VOL_SURFACE_PER_EXPIRY') == '1'
    missing = []
    for name in sorted(spec_names - runtime_names):
        if (not flag) and name in {'g6_vol_surface_rows_expiry'}:
            continue
        missing.append(name)

    if missing:
        print("Spec metrics missing from runtime registry (import side effects incomplete or name drift):")
        for n in missing:
            print(f"  - {n}")
        # Also dump a small JSON to help inspect in CI artifacts if needed
        summary = {
            'missing': missing,
            'runtime_count': len(runtime_names),
            'spec_count': len(spec_names),
        }
        print("SUMMARY:")
        print(json.dumps(summary, indent=2))
        return 1

    print("OK: metrics spec matches runtime registry surface (allowing env-gated exceptions)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
