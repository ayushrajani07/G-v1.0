"""
Configuration module for G6 Platform.

Canonical config loading:
    from src.config.loader import load_and_validate_config
    config = load_and_validate_config('config/platform_config.json')

Phase 2 consolidation: config_loader.py merged into loader.py
"""
import os
import sys  # retained for backward compatibility logging or future use

from .loader import load_and_validate_config, load_config, create_default_config  # Canonical loader


__all__ = [
    'load_and_validate_config',  # Canonical
    'load_config',  # Returns ConfigWrapper
    'create_default_config',  # Utility for testing/fallback
]
