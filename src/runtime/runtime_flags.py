"""Centralized runtime flags parsing.

Loads environment-driven feature toggles once; exposes a lightweight dataclass
for injection into hot paths (provider filtering). Avoids repeated os.getenv.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from src.config.env_config import EnvConfig

TRUE_SET = {'1','true','yes','on'}

def _is_true(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.lower() in TRUE_SET

@dataclass(slots=True)
class RuntimeFlags:
    match_mode: str
    underlying_strict: bool
    safe_mode: bool
    enable_forward_fallback: bool
    enable_backward_fallback: bool
    trace_collector: bool
    trace_option_match: bool
    prefilter_disabled: bool

    @classmethod
    def load(cls) -> RuntimeFlags:
        return cls(
            match_mode=EnvConfig.get_str('G6_SYMBOL_MATCH_MODE','strict').strip().lower(),
            underlying_strict=EnvConfig.get_bool('G6_SYMBOL_MATCH_UNDERLYING_STRICT', True),
            safe_mode=EnvConfig.get_bool('G6_SYMBOL_MATCH_SAFEMODE', True),
            enable_forward_fallback=EnvConfig.get_bool('G6_ENABLE_NEAREST_EXPIRY_FALLBACK', True),
            enable_backward_fallback=EnvConfig.get_bool('G6_ENABLE_BACKWARD_EXPIRY_FALLBACK', True),
            trace_collector=EnvConfig.get_bool('G6_TRACE_COLLECTOR', False),
            trace_option_match=EnvConfig.get_bool('G6_TRACE_OPTION_MATCH', False),
            prefilter_disabled=EnvConfig.get_bool('G6_DISABLE_PREFILTER', False),
        )

# Lightweight module-level singleton cache (reloadable manually if needed)
_cached: RuntimeFlags | None = None

def get_flags(force_reload: bool = False) -> RuntimeFlags:
    global _cached  # noqa: PLW0603
    if force_reload or _cached is None:
        _cached = RuntimeFlags.load()
    return _cached
