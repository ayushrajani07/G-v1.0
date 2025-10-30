"""Memory Pressure Evaluation (initial stub)

Derives a simple memory tier (0 good, 1 warning, 2 critical) using RSS against
configured thresholds if available. Falls back to environment variable
`G6_MEMORY_TIER` when explicit override is provided.

Threshold Sources:
 - Env overrides: G6_MEMORY_LEVEL1_MB, G6_MEMORY_LEVEL2_MB (critical defaults to level2 * 1.2 if LEVEL3 unset)
 - Optional explicit G6_MEMORY_LEVEL3_MB

Implementation presently uses `psutil` if installed; otherwise no-op unless
explicit tier override exists. Designed to be soft (never raises) and minimal
overhead (single RSS fetch per cycle when enabled).
"""
from __future__ import annotations

import os
import time

from src.config.env_config import EnvConfig

try:  # psutil optional
    import psutil
except Exception:  # pragma: no cover
    psutil = None


def evaluate_memory_tier(ctx) -> None:
    # Explicit override tier (simulate) takes precedence
    override = EnvConfig.get_str('G6_MEMORY_TIER_OVERRIDE', '') or EnvConfig.get_str('G6_MEMORY_TIER', '')
    if override:
        try:
            ctx.set_flag('memory_tier', int(override))
        except Exception:
            pass
        return
    # Optional TTL cache to avoid repeated psutil.Process() creation and
    # RSS sampling overhead in hot paths. Controlled via env
    # G6_MEMORY_TIER_TTL_MS or G6_MEMORY_TIER_TTL_SEC (disabled by default).
    try:
        ms_str = EnvConfig.get_str('G6_MEMORY_TIER_TTL_MS', '')
        if ms_str:
            _ttl = max(0.0, float(ms_str) / 1000.0)
        else:
            s_str = EnvConfig.get_str('G6_MEMORY_TIER_TTL_SEC', '')
            _ttl = max(0.0, float(s_str)) if s_str else 0.0
    except Exception:
        _ttl = 0.0
    # Module-level cache
    if _ttl:
        try:
            # Keep simple state on the ctx if available to avoid global state
            cache = getattr(ctx, '_memory_tier_cache', None)
            now = time.time()
            if cache and (now - cache.get('ts', 0)) < _ttl:
                # reuse last-tier
                try:
                    ctx.set_flag('memory_tier', int(cache.get('tier', 0)))
                except Exception:
                    pass
                return
        except Exception:
            pass
    # If psutil missing, skip auto evaluation
    if psutil is None:
        return
    try:
        proc = psutil.Process()
        rss_bytes = proc.memory_info().rss
        rss_mb = rss_bytes / (1024 * 1024)
        lvl1 = EnvConfig.get_float('G6_MEMORY_LEVEL1_MB', 200.0)
        lvl2 = EnvConfig.get_float('G6_MEMORY_LEVEL2_MB', 300.0)
        lvl3 = EnvConfig.get_float('G6_MEMORY_LEVEL3_MB', lvl2 * 1.2)
        tier = 0
        if rss_mb >= lvl3:
            tier = 2
        elif rss_mb >= lvl1 or rss_mb >= lvl2:  # if between lvl1 and lvl3 treat as warning
            tier = 1
        ctx.set_flag('memory_tier', tier)
        # store into cache if requested
        try:
            if _ttl:
                cache = {'ts': time.time(), 'tier': int(tier)}
                try:
                    ctx._memory_tier_cache = cache
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:  # pragma: no cover
        # Silent failure acceptable; adaptive controller will fallback to default tier 0
        return

__all__ = ["evaluate_memory_tier"]
