from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .._index_norm import normalize_index
from .._date_norm import resolve_date
from .._now_norm import infer_now_ms_from_rows

from ._bands_archive import iter_bands_quantile_rows
from ._api_contract import base_headers


async def handle_path_prediction_history(
    *,
    index: str,
    horizon_minutes: int,
    expiry_tag: str,
    offset: str,
    window_minutes: int,
    bucket_ms: int,
    date_str: Optional[str],
    mode: str,
    limit: int,
    prefix: str,
    profile: Optional[str],
    # injected deps
    project_root: Callable[[], object],
    normalize_expiry_tag: Callable[[str, str], str],
    find_live_csv: Callable[..., object],
    load_csv_rows_full: Callable[[object], list[dict]],
) -> JSONResponse:
    """Implementation of /api/ml/path_prediction_history extracted from router."""

    try:
        from datetime import datetime

        idx = normalize_index(index)
        the_date = resolve_date(date_str)

        hdr_base = base_headers(
            route_version="predhist-v1",
            index=idx,
            date=(the_date.isoformat() if the_date else None),
        )
        try:
            hdr_base["X-Expiry-Tag"] = str(expiry_tag or "")
            hdr_base["X-Offset"] = str(offset or "")
            hdr_base["X-Profile"] = (str(profile).lower() if profile else "")
        except (TypeError, ValueError, AttributeError):
            pass

        # Resolve 'now' via live_csv for robust windowing (falls back to archive if needed)
        eff_tag = normalize_expiry_tag(idx, expiry_tag)
        p_live = find_live_csv((project_root() / "data" / "g6_data"), idx, eff_tag, offset, the_date)
        now_ms: Optional[int] = None
        try:
            if p_live and getattr(p_live, "exists")():
                rows = load_csv_rows_full(p_live)
                if rows:
                    now_ms = infer_now_ms_from_rows(rows)
        except BaseException as e:
            import asyncio
            if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                raise
            now_ms = None

        # Locate bands archive for the day
        arch_dir = project_root() / "data" / "ml" / "path_forecasts" / idx
        day_str = the_date.strftime("%Y-%m-%d")
        arch_file_bands = arch_dir / f"{day_str}_bands.csv"
        if not arch_file_bands.exists():
            hdr_base["X-Empty-Reason"] = "bands_archive_missing"
            return JSONResponse([], headers=hdr_base)

        # Read rows for the requested horizon
        entries: list[tuple[int, int, Optional[float], Optional[float], Optional[float]]] = []
        for gen_ms, tgt_ms, _hmin, qvals, _band_scale in iter_bands_quantile_rows(
            arch_file_bands,
            quantiles=[10, 50, 90],
            horizon_min=int(horizon_minutes),
            profile=profile,
        ):
            q10v = qvals.get(10)
            q50v = qvals.get(50)
            q90v = qvals.get(90)
            entries.append((gen_ms, tgt_ms, q10v, q50v, q90v))

        if not entries:
            hdr_base["X-Empty-Reason"] = "no_band_rows"
            return JSONResponse([], headers=hdr_base)

        # Sort by generation time and window-filter
        entries.sort(key=lambda x: x[0])
        if now_ms is None:
            now_ms = entries[-1][0]
        cutoff = int(now_ms) - int(window_minutes) * 60_000
        filtered = [e for e in entries if e[0] >= cutoff]

        # Optional bucketing by generation time: keep last per bucket
        if bucket_ms and bucket_ms > 1_000:
            bucketed: dict[int, tuple[int, int, Optional[float], Optional[float], Optional[float]]] = {}
            for e in filtered:
                b = (e[0] // int(bucket_ms)) * int(bucket_ms)
                bucketed[b] = e
            filtered = [bucketed[k] for k in sorted(bucketed.keys())]

        # Enforce limit: keep most recent 'limit' entries
        if len(filtered) > int(limit):
            filtered = filtered[-int(limit) :]

        out: list[dict[str, object]] = []
        want_full = mode == "full"
        for gen_ms, tgt_ms, q10v, q50v, q90v in filtered:
            out_row: dict[str, object] = {
                "plot_time": datetime.utcfromtimestamp(int(gen_ms) / 1000.0)
                .replace(microsecond=0)
                .isoformat()
                + "Z",
                "gen_ms": int(gen_ms),
                "target_ms": int(tgt_ms),
                f"{prefix}q50": (max(0.0, float(q50v)) if isinstance(q50v, (int, float)) else None),
            }
            if want_full:
                out_row[f"{prefix}q10"] = (max(0.0, float(q10v)) if isinstance(q10v, (int, float)) else None)
                out_row[f"{prefix}q90"] = (max(0.0, float(q90v)) if isinstance(q90v, (int, float)) else None)
            out.append(out_row)

        return JSONResponse(out)

    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
