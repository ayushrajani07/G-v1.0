from __future__ import annotations

from typing import Any, Optional


def base_headers(*, route_version: str, index: str, date: Optional[str] = None) -> dict[str, str]:
    hdr = {
        "X-Route-Version": str(route_version),
        "X-Index": str(index),
        "X-Date": str(date or ""),
    }
    return hdr


def error_payload(
    *,
    error: str,
    index: str,
    expiry_tag: Optional[str] = None,
    offset: Optional[str] = None,
    date: Optional[str] = None,
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "error": str(error),
        "index": str(index),
        "expiry_tag": (str(expiry_tag) if expiry_tag is not None else None),
        "offset": (str(offset) if offset is not None else None),
        "date": (str(date) if date is not None else None),
    }
    out.update(extra)
    return out
