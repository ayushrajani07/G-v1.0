"""Central version metadata for G6 Platform.

Single authoritative place for the platform version to decouple build
info helpers and eliminate legacy imports.

Resolution order for get_version():
1. Env override G6_VERSION (e.g., injected by CI)
2. __version__ constant below

Update the __version__ value during release tagging.
"""
from __future__ import annotations

# Phase 2: Centralized environment variable access
from src.config.env_config import EnvConfig

__version__ = "0.0.0-dev"

def get_version() -> str:
    return EnvConfig.get_str("G6_VERSION", __version__)

__all__ = ["__version__", "get_version"]
