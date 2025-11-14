"""Simple in-memory TTL cache helpers used by HTTP routes.

Notes:
- Process-local only; suitable for single-uvicorn-worker dev usage.
- Values are stored as-is; TTL enforced on get.
"""
from __future__ import annotations

from typing import Any, Dict
import time

_STORE: Dict[str, Dict[str, Dict[str, Any]]] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def cache_get(namespace: str, key: str, ttl_ms: int) -> Any | None:
    try:
        ns = _STORE.get(namespace)
        if not ns:
            return None
        obj = ns.get(key)
        if not obj:
            return None
        ts = int(obj.get("__ts", 0))
        if ttl_ms and ttl_ms > 0:
            if ts + int(ttl_ms) < _now_ms():
                # expired
                try:
                    del ns[key]
                except Exception:
                    pass
                return None
        # return shallow copy without metadata key
        out = dict(obj)
        try:
            out.pop("__ts", None)
        except Exception:
            pass
        return out
    except Exception:
        return None


def cache_set(namespace: str, key: str, value: Dict[str, Any]) -> None:
    try:
        ns = _STORE.setdefault(namespace, {})
        payload = dict(value)
        payload["__ts"] = _now_ms()
        ns[key] = payload
    except Exception:
        return


__all__ = ["cache_get", "cache_set"]