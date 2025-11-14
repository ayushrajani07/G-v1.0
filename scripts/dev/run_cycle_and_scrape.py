#!/usr/bin/env python3
"""Run a single orchestrator cycle in-process and scrape metrics.

Purpose: Debug end-of-cycle gauges updating by ensuring the same process
produces and serves metrics on the default Prometheus registry.

Environment presets:
- G6_DISABLE_AUTH_PREFLIGHT=1
- G6_ALLOW_PROVIDERLESS_CYCLES=1
- G6_LOOP_MARKET_HOURS=0
- G6_DISABLE_COMPONENTS=1

Outputs a compact block with the four key gauges and histogram presence.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> int:
    os.environ.setdefault('G6_DISABLE_AUTH_PREFLIGHT', '1')
    os.environ.setdefault('G6_ALLOW_PROVIDERLESS_CYCLES', '1')
    os.environ.setdefault('G6_LOOP_MARKET_HOURS', '0')
    os.environ.setdefault('G6_DISABLE_COMPONENTS', '1')
    os.environ.setdefault('G6_SINGLE_HEADER_MODE', '1')
    os.environ.setdefault('G6_FORCE_NEW_REGISTRY', '1')

    # Ensure project root on sys.path for `src` imports
    try:
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
    except Exception:
        pass
    from src.orchestrator.bootstrap import bootstrap_runtime
    from src.orchestrator.cycle import run_cycle
    from src.config.env_config import EnvConfig

    # Start metrics server + registry fresh
    ctx, _closer = bootstrap_runtime('config/g6_config.json', reset_metrics=True, custom_registry=False)

    # Ensure we have indices to avoid early no-op
    try:
        raw_cfg = ctx.config.raw if hasattr(ctx.config, 'raw') else {}
        if ctx.index_params is None:
            idx_params = raw_cfg.get('index_params') or raw_cfg.get('indices') or {}
            if isinstance(idx_params, dict) and idx_params:
                ctx.index_params = idx_params  # type: ignore[attr-defined]
            else:
                if EnvConfig.get_bool('G6_ALLOW_PROVIDERLESS_CYCLES', False):
                    ctx.index_params = { 'NIFTY': { 'enable': True } }  # type: ignore[attr-defined]
    except Exception:
        pass

    # Run a single cycle and wait a beat for any async emitters
    elapsed = run_cycle(ctx)
    time.sleep(0.5)

    # Scrape in-process registry to avoid cross-process confusion
    from prometheus_client import REGISTRY, generate_latest
    blob = generate_latest(REGISTRY).decode('utf-8', errors='ignore')
    want = (
        'g6_collection_cycle_time_seconds',
        'g6_cycles_per_hour',
        'g6_options_processed_per_minute',
        'g6_collection_success_rate_percent',
        'g6_cycle_write_time_seconds_sum',
        'g6_cycle_write_time_seconds_count',
        'g6_cycle_process_time_seconds_sum',
        'g6_cycle_process_time_seconds_count',
        'g6_cycle_fetch_time_seconds_sum',
        'g6_cycle_fetch_time_seconds_count',
    )
    lines = []
    for line in blob.splitlines():
        if any(key in line for key in want):
            lines.append(line)

    print(f"elapsed={elapsed:.3f}s")
    print("\n".join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
