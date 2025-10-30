from __future__ import annotations

"""Environment adapter for collectors.

Provides consistent helpers to parse environment variables with sane defaults
and shared truthy semantics. Centralizes behavior to simplify testing and
future governance (e.g., lint for direct os.getenv usage).

NOTE: This adapter now delegates to src.config.env_config for consistency.
"""
import os
from collections.abc import Callable

from src.config.env_config import EnvConfig

_TRUTHY = {"1","true","yes","on","y"}

def get_str(name: str, default: str = "") -> str:
    return EnvConfig.get_str(name, default)

def get_bool(name: str, default: bool = False) -> bool:
    return EnvConfig.get_bool(name, default)

def get_int(name: str, default: int) -> int:
    return EnvConfig.get_int(name, default)

def get_float(name: str, default: float) -> float:
    return EnvConfig.get_float(name, default)

def get_csv(name: str, default: list[str] | None = None, *, sep: str = ",", transform: Callable[[str], str] | None = None) -> list[str]:
    try:
        v = EnvConfig.get_str(name, "")
        if not v:
            return list(default or [])
        parts = [p.strip() for p in v.split(sep) if p.strip()]
        if transform:
            parts = [transform(p) for p in parts]
        return parts
    except Exception:
        return list(default or [])

__all__ = [
    "get_str",
    "get_bool",
    "get_int",
    "get_float",
    "get_csv",
]
