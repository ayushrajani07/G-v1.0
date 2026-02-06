from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from ._api_contract import base_headers


async def handle_path_coverage_history_csv(
    *,
    index: str,
    horizon: int,
    window_minutes: int,
    history_minutes: int,
    step_minutes: int,
    expiry_tag: str,
    offset: str,
    bucket_ms: int,
    date_str: Optional[str],
    max_points: int,
    # injected deps
    compute_json: Callable[..., Awaitable[JSONResponse]],
) -> PlainTextResponse:
    """Implementation of /api/ml/path_coverage_history_csv extracted from router."""

    try:
        # Reuse JSON endpoint to compute payload
        resp = await compute_json(
            index=index,
            horizon=horizon,
            window_minutes=window_minutes,
            history_minutes=history_minutes,
            step_minutes=step_minutes,
            expiry_tag=expiry_tag,
            offset=offset,
            bucket_ms=bucket_ms,
            date_str=date_str,
            max_points=max_points,
        )

        import json

        hdr_base: dict[str, str] = {}
        if isinstance(resp, JSONResponse):
            try:
                hdr_base = dict(resp.headers)
            except (TypeError, ValueError):
                hdr_base = {}
        if not hdr_base:
            hdr_base = base_headers(route_version="covhistcsv-v1", index=str(index), date=(date_str or None))
        else:
            hdr_base["X-Route-Version"] = "covhistcsv-v1"

        data = []
        if isinstance(resp, JSONResponse):
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
                if "X-Empty-Reason" not in hdr_base:
                    hdr_base["X-Empty-Reason"] = "json_parse_failed"
                data = []

        # Build CSV
        import io
        import csv as _csv

        buf = io.StringIO()
        w = _csv.writer(buf)
        w.writerow(["ts_iso", "ts_ms", "coverage", "target", "gap_abs", "samples", "band_scale"])
        for o in data:
            w.writerow(
                [
                    (o.get("ts_iso") or ""),
                    (o.get("ts_ms") or ""),
                    (o.get("coverage") if o.get("coverage") is not None else ""),
                    (o.get("target") if o.get("target") is not None else ""),
                    (o.get("gap_abs") if o.get("gap_abs") is not None else ""),
                    (o.get("samples") or 0),
                    (o.get("band_scale") if o.get("band_scale") is not None else ""),
                ]
            )

        if not data and "X-Empty-Reason" not in hdr_base:
            hdr_base["X-Empty-Reason"] = "no_rows"
        return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers=hdr_base)

    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
