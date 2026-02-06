from __future__ import annotations

import os
from typing import Any

def detect_hotreload_trigger(headers: Any = None, path: str | None = None) -> bool:
    """Return False.

    Dynamic hot-reload triggers were intentionally removed.
    """
    return False


__all__ = ['detect_hotreload_trigger']
