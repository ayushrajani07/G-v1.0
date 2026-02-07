from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import HTTPException, Query
from fastapi.responses import PlainTextResponse

from src.utils.timeutils import utc_now_z as _utc_now_z

from ...core import paths as _paths
from .._index_norm import normalize_index

try:  # pragma: no cover - optional dependency
    from src.path_forecast.composite import CompositePathForecaster, CompositeConfig
except BaseException as e:  # pragma: no cover
    if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
        raise
    CompositePathForecaster = None  # type: ignore
    CompositeConfig = None  # type: ignore


async def api_ml_forecast_path(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: int = Query(60, ge=1, le=24 * 60, description="Forecast horizon in minutes"),
    quantiles: str = Query("0.1,0.5,0.9", description="Comma-separated quantiles (e.g. 0.1,0.5,0.9)"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Bucket size for future timestamps (ms)"),
) -> PlainTextResponse:
    """Return composite path forecast quantiles as CSV.

    CSV header: timestamp,index,horizon,quantile,future_ts,value

    Falls back to placeholder NAN rows if the optional forecaster is unavailable.
    """
    try:
        idx_norm = normalize_index(index)
        req_ts = _utc_now_z()

        q_list: list[float] = []
        for part in str(quantiles).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                q_list.append(float(part))
            except (TypeError, ValueError):
                continue
        if not q_list:
            q_list = [0.1, 0.5, 0.9]

        header = "timestamp,index,horizon,quantile,future_ts,value"

        if CompositePathForecaster is None or CompositeConfig is None:
            now_ms = int(time.time() * 1000)
            rows = [
                f"{req_ts},{idx_norm},{horizon},{q:.3f},{now_ms + bucket_ms},{float('nan')}" for q in q_list
            ]
            return PlainTextResponse("\n".join([header, *rows]), media_type="text/csv")

        try:
            root = _paths.project_root() / "data" / "g6_data"
        except (AttributeError, TypeError, ValueError, OSError):
            root = Path("data/g6_data")

        try:
            cfg = CompositeConfig(root=root, window=60, k=15, min_days=3)
            fore = CompositePathForecaster(cfg)
            now_ms = int(time.time() * 1000)
            times, qmap = fore.forecast_path(
                [],
                context={"index": idx_norm, "now_ms": now_ms, "live_rows": []},
                quantiles=q_list,
                horizon_minutes=int(horizon),
                bucket_ms=int(bucket_ms),
            )
            rows: list[str] = []
            for q in q_list:
                vals = list(qmap.get(q, []))
                rows.extend(
                    f"{req_ts},{idx_norm},{horizon},{q:.3f},{ft},{(vals[i] if i < len(vals) else float('nan'))}"
                    for i, ft in enumerate(times)
                )
            return PlainTextResponse("\n".join([header, *rows]), media_type="text/csv")
        except BaseException as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                raise
            now_ms = int(time.time() * 1000)
            rows = [
                f"{req_ts},{idx_norm},{horizon},{q:.3f},{now_ms + bucket_ms},{float('nan')}" for q in q_list
            ]
            return PlainTextResponse("\n".join([header, *rows]), media_type="text/csv")

    except HTTPException:
        raise
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
