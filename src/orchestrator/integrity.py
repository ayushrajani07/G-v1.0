from __future__ import annotations

import json
import os
from typing import Any

# Simple in-module cache keyed by (path, mtime_ns, size)
_INTEGRITY_CACHE: dict[str, Any] = {
    'path': None,
    'mtime_ns': 0,
    'size': 0,
    'result': None,
}


def integrity_from_events(events_path: str, limit: int = 200_000) -> dict[str, Any]:
    """Compute a compact integrity summary from an events log.

    Uses a lightweight cache keyed by file (path, mtime_ns, size) to avoid
    re-reading large logs when unchanged.
    """
    try:
        st = os.stat(events_path)
        mtime_ns = int(getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))
        size = int(st.st_size)
    except FileNotFoundError:
        return {
            'cycles_observed': 0,
            'first_cycle': None,
            'last_cycle': None,
            'missing_count': 0,
            'status': 'OK',
            'source': 'http_inline',
        }
    except Exception:
        mtime_ns = -1
        size = -1

    cache = _INTEGRITY_CACHE
    if cache.get('path') == events_path and cache.get('mtime_ns') == mtime_ns and cache.get('size') == size:
        res = cache.get('result')
        if isinstance(res, dict):
            return res

    cycles: list[int] = []
    try:
        with open(events_path, encoding='utf-8') as fh:
            for i, line in enumerate(fh):
                if i >= limit:
                    break
                if 'cycle_start' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get('event') == 'cycle_start':
                    c = (obj.get('context') or {}).get('cycle')
                    if isinstance(c, int):
                        cycles.append(c)
    except FileNotFoundError:
        cycles = []

    missing = 0
    if cycles:
        cs = sorted(set(cycles))
        for a, b in zip(cs, cs[1:], strict=False):
            if b > a + 1:
                missing += (b - a - 1)

    result = {
        'cycles_observed': len(cycles),
        'first_cycle': min(cycles) if cycles else None,
        'last_cycle': max(cycles) if cycles else None,
        'missing_count': missing,
        'status': 'OK' if missing == 0 else 'GAPS',
        'source': 'http_inline',
    }
    if mtime_ns >= 0 and size >= 0:
        cache['path'] = events_path
        cache['mtime_ns'] = mtime_ns
        cache['size'] = size
        cache['result'] = result
    return result


__all__ = ["integrity_from_events"]
