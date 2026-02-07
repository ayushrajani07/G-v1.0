from __future__ import annotations

from typing import Any, Optional


def iso_from_ms(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        import datetime as _dt

        return _dt.datetime.fromtimestamp(int(ms) / 1000).replace(microsecond=0).isoformat()
    except (OverflowError, OSError, TypeError, ValueError):
        return ""


def base_headers(*, route_version: str, index: str, date: Optional[str] = None) -> dict[str, str]:
    hdr = {
        "X-Route-Version": str(route_version),
        "X-Index": str(index),
        "X-Date": str(date or ""),
    }
    return hdr


def add_common_headers(
    hdr: dict[str, str],
    *,
    expiry_tag: Optional[str] = None,
    offset: Optional[str] = None,
    profile: Optional[str] = None,
    gen_ms: int | None = None,
) -> dict[str, str]:
    try:
        hdr["X-Expiry-Tag"] = str(expiry_tag or "")
        hdr["X-Offset"] = str(offset or "")
        if profile is not None:
            hdr["X-Profile"] = str(profile).lower() if profile else ""
        if gen_ms is not None:
            hdr["X-Gen-Ms"] = str(gen_ms or "")
            hdr["X-Gen-Iso"] = iso_from_ms(gen_ms)
    except (AttributeError, TypeError, ValueError):
        pass
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
