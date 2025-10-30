#!/usr/bin/env python3
"""CollectorSettings

Centralized parsing of environment-driven collector configuration flags.
Phase 0 extraction: ONLY moves existing flag reads used inside expiry processing.

Flags migrated (legacy env names preserved):
  G6_FILTER_MIN_VOLUME -> min_volume
  G6_FILTER_MIN_OI -> min_oi
  G6_FILTER_VOLUME_PERCENTILE -> volume_percentile
  G6_FOREIGN_EXPIRY_SALVAGE -> salvage_enabled
  G6_DOMAIN_MODELS -> domain_models_enabled

Design notes:
- Parsing is tolerant: invalid ints/floats fall back to defaults.
- Boolean flags accept 1/true/yes/on (case-insensitive).
- Access pattern: settings = CollectorSettings.from_env(); pass into process_expiry.
- Backward compatibility: existing code paths not yet updated continue to read os.environ unaffected.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import ClassVar

from src.config.env_config import EnvConfig


@dataclass(slots=True)
class CollectorSettings:
    min_volume: int = 0
    min_oi: int = 0
    volume_percentile: float = 0.0
    salvage_enabled: bool = False
    domain_models_enabled: bool = False

    # Future extension placeholder (avoid churn in constructor):
    # e.g. retry_on_empty: bool = False

    BOOL_ENV_MAP: ClassVar[dict[str,str]] = {
        'salvage_enabled': 'G6_FOREIGN_EXPIRY_SALVAGE',
        'domain_models_enabled': 'G6_DOMAIN_MODELS',
    }
    INT_ENV_MAP: ClassVar[dict[str,str]] = {
        'min_volume': 'G6_FILTER_MIN_VOLUME',
        'min_oi': 'G6_FILTER_MIN_OI',
    }
    FLOAT_ENV_MAP: ClassVar[dict[str,str]] = {
        'volume_percentile': 'G6_FILTER_VOLUME_PERCENTILE',
    }

    @classmethod
    def from_env(cls) -> CollectorSettings:  # pragma: no cover - simple parsing
        kw = {}
        for attr, env_name in cls.INT_ENV_MAP.items():
            kw[attr] = EnvConfig.get_int(env_name, 0)
        for attr, env_name in cls.FLOAT_ENV_MAP.items():
            kw[attr] = EnvConfig.get_float(env_name, 0.0)
        for attr, env_name in cls.BOOL_ENV_MAP.items():
            kw[attr] = EnvConfig.get_bool(env_name, False)
        return cls(**kw)

    def as_dict(self) -> dict:
        return {
            'min_volume': self.min_volume,
            'min_oi': self.min_oi,
            'volume_percentile': self.volume_percentile,
            'salvage_enabled': self.salvage_enabled,
            'domain_models_enabled': self.domain_models_enabled,
        }

__all__ = ["CollectorSettings"]
