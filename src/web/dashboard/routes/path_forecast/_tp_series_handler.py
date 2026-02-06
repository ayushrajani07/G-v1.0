from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .._index_norm import normalize_index
from .._date_norm import resolve_date
from .._now_norm import infer_now_ms_from_rows

from ._api_contract import base_headers


async def handle_live_tp_series(
    *,
    index: str,
    expiry_tag: str,
    offset: str,
    date_str: Optional[str],
    window_minutes: int,
    bucket_ms: int,
    # injected deps
    project_root: Callable[[], object],
    normalize_expiry_tag: Callable[[str, str], str],
    find_live_csv: Callable[..., object],
    load_csv_rows_full: Callable[[object], list[dict]],
    extract_tp: Callable[[dict], object],
) -> JSONResponse:
    """Implementation of /api/ml/live_tp_series extracted from router."""

    try:
        from datetime import datetime

        idx = normalize_index(index)
        the_date = resolve_date(date_str)

        hdr_base = base_headers(
            route_version="tpseries-v1",
            index=idx,
            date=(the_date.isoformat() if the_date else None),
        )
        try:
            hdr_base["X-Expiry-Tag"] = str(expiry_tag or "")
            hdr_base["X-Offset"] = str(offset or "")
        except (TypeError, ValueError):
            pass

        eff_tag = normalize_expiry_tag(idx, expiry_tag)
        p = find_live_csv((project_root() / "data" / "g6_data"), idx, eff_tag, offset, the_date)
        try:
            if (not p) or (not getattr(p, "exists")()):
                hdr_base["X-Empty-Reason"] = "live_csv_not_found"
                return JSONResponse([], status_code=200, headers=hdr_base)
        except (AttributeError, TypeError):
            hdr_base["X-Empty-Reason"] = "live_csv_not_found"
            return JSONResponse([], status_code=200, headers=hdr_base)

        rows = load_csv_rows_full(p)
        if not rows:
            hdr_base["X-Empty-Reason"] = "no_live_rows"
            return JSONResponse([], status_code=200, headers=hdr_base)

        # establish cutoff and build series
        try:
            now_ms = infer_now_ms_from_rows(rows)
        except (TypeError, ValueError, KeyError):
            now_ms = None
        if now_ms is None:
            hdr_base["X-Empty-Reason"] = "no_now_ms"
            return JSONResponse([], status_code=200, headers=hdr_base)

        cutoff = int(now_ms) - int(window_minutes) * 60_000
        out: list[dict[str, object]] = []
        for r in rows:
            try:
                tms = int(r.get("ts") or r.get("time") or 0)
            except (TypeError, ValueError):
                continue
            if not tms or tms < cutoff:
                continue
            v = extract_tp(r)
            val = None
            if isinstance(v, (int, float)):
                val = float(v)
                if val < 0:
                    val = 0.0
            out.append(
                {
                    "plot_time": datetime.utcfromtimestamp(tms / 1000.0)
                    .replace(microsecond=0)
                    .isoformat()
                    + "Z",
                    "tp": val,
                }
            )

        # Optional thinning to bucket grid to reduce points
        if bucket_ms and bucket_ms > 1_000:
            bucketed: dict[int, dict[str, object]] = {}
            for o in out:
                try:
                    from datetime import datetime as _dtpy

                    ms = int(
                        _dtpy.fromisoformat(str(o["plot_time"]).rstrip("Z"))
                        .replace(tzinfo=None)
                        .timestamp()
                        * 1000
                    )
                except (TypeError, ValueError, KeyError):
                    ms = None
                if ms is None:
                    continue
                b = (ms // int(bucket_ms)) * int(bucket_ms)
                bucketed[b] = o
            out = [bucketed[k] for k in sorted(bucketed.keys())]

        return JSONResponse(out, headers=hdr_base)

    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))


async def handle_tp_series_alias(
    *,
    index: str,
    expiry_tag: str,
    offset: str,
    date_str: Optional[str],
    window_minutes: int,
    bucket_ms: int,
    # injected deps
    live_tp_series: Callable[..., object],
):
    """Alias for /api/ml/live_tp_series to avoid dashboard/plugin caching issues."""

    return await live_tp_series(
        index=index,
        expiry_tag=expiry_tag,
        offset=offset,
        date_str=date_str,
        window_minutes=window_minutes,
        bucket_ms=bucket_ms,
    )
