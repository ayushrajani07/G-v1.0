from __future__ import annotations

import os
from typing import Any

from src.config.env_config import EnvConfig


def detect_hotreload_trigger(headers: Any = None, path: str | None = None) -> bool:
    """Return True if any configured hot-reload triggers are present.

    Triggers:
      - Env: G6_CATALOG_HTTP_HOTRELOAD=1
      - Env: G6_CATALOG_HTTP_FORCE_RELOAD=1 (backward-compatible)
      - Header: X-G6-HotReload: 1|true|yes|on
      - Query: ?hotreload=1 (or ?hot=1) on the request path

    Pure detection only; callers perform actual reload.
    """
    try:
        trigger = False
        if EnvConfig.get_bool('G6_CATALOG_HTTP_HOTRELOAD', False):
            trigger = True
        if EnvConfig.get_bool('G6_CATALOG_HTTP_FORCE_RELOAD', False):
            trigger = True
        try:
            if headers:
                hv = headers.get('X-G6-HotReload')
                if hv and str(hv).strip().lower() in ('1','true','yes','on'):
                    trigger = True
        except Exception:
            pass
        try:
            if path and '?' in path:
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(path).query or '')
                hv = (q.get('hotreload') or q.get('hot') or [''])[0]
                if hv and str(hv).strip().lower() in ('1','true','yes','on'):
                    trigger = True
        except Exception:
            pass
        return trigger
    except Exception:
        return False


__all__ = ['detect_hotreload_trigger']
