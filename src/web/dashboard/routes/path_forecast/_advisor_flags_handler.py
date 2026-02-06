from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse


async def handle_path_advisor_flags(
    *,
    index: str,
    horizon: int,
    window_minutes: int,
    expiry_tag: str,
    offset: str,
    bucket_ms: int,
    date_str: Optional[str],
    gap_warn: float,
    gap_crit: float,
    min_samples_warn: int,
    min_samples_crit: int,
    # injected deps
    compute_advisor: Callable[..., Awaitable[JSONResponse]],
) -> JSONResponse:
    """Implementation of /api/ml/path_advisor_flags extracted from router."""

    try:
        resp = await compute_advisor(
            index=index,
            horizon=horizon,
            window_minutes=window_minutes,
            expiry_tag=expiry_tag,
            offset=offset,
            bucket_ms=bucket_ms,
            date_str=date_str,
            gap_warn=gap_warn,
            gap_crit=gap_crit,
            min_samples_warn=min_samples_warn,
            min_samples_crit=min_samples_crit,
        )

        import json

        data = {}
        rb = resp.body
        try:
            if isinstance(rb, (bytes, bytearray)):
                s = rb.decode("utf-8")
            elif isinstance(rb, memoryview):
                s = rb.tobytes().decode("utf-8")
            else:
                s = str(rb)
            data = json.loads(s)
        except (UnicodeError, TypeError, ValueError):
            data = {}

        sm = (data or {}).get("summary") or {}
        band_scale = sm.get("band_scale")
        sat_hi = 1 if (isinstance(band_scale, (int, float)) and float(band_scale) >= 4.9) else 0
        sat_lo = 1 if (isinstance(band_scale, (int, float)) and float(band_scale) <= 0.55) else 0
        fallback = 1 if bool(sm.get("fallback")) else 0

        out = {
            "fallback": int(fallback),
            "sat_hi": int(sat_hi),
            "sat_lo": int(sat_lo),
            "gap_abs": sm.get("gap_abs"),
            "samples": sm.get("samples") or 0,
            "band_scale": band_scale,
        }
        return JSONResponse(out)

    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
