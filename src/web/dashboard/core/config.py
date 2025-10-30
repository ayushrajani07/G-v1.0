from __future__ import annotations

import os

from src.config.env_config import EnvConfig

# Centralized configuration helpers and constants

# Concurrency guard for heavy endpoints (live_csv, overlay)
MAX_CONCURRENCY: int = max(1, EnvConfig.get_int("G6_LIVE_API_MAX_CONCURRENCY", 4))

# CSV rows cache capacity
CSV_CACHE_MAX: int = max(1, EnvConfig.get_int("G6_CSV_CACHE_MAX", 32))

# Grafana port hint (for CORS diagnostics only)
GRAFANA_PORT: str = EnvConfig.get_str("G6_GRAFANA_PORT", "3002").strip()

# Development CORS override flag ("1" enables allow-all)
CORS_ALL: str = EnvConfig.get_str("G6_CORS_ALL", "0").strip()

# Web workers hint for diagnostics
WEB_WORKERS: str = EnvConfig.get_str("G6_WEB_WORKERS", "1").strip()
