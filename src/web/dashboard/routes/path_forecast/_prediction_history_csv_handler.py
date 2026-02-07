from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

from .._date_norm import resolve_date
from .._now_norm import infer_now_ms_from_rows

from ._bands_archive import detect_quantile_columns, iter_dict_rows, parse_float, parse_int
from ._api_contract import base_headers
from ._archive_paths import bands_archive_path


async def handle_path_prediction_history_csv(
    *,
    index: str,
    horizon_minutes: int,
    expiry_tag: str,
    offset: str,
    window_minutes: int,
    bucket_ms: int,
    date_str: Optional[str],
    prefix: str,
    # injected deps
    normalize_index: Callable[[str], str],
    project_root: Callable[[], object],
    normalize_expiry_tag: Callable[[str, str], str],
    find_live_csv: Callable[..., object],
    load_csv_rows_full: Callable[[object], list[dict]],
) -> PlainTextResponse:
    """Implementation of /api/ml/path_prediction_history_csv extracted from router."""

    try:
        from datetime import datetime
        import csv
        from io import StringIO

        idx = normalize_index(index)
        the_date = resolve_date(date_str)

        hdr_base = base_headers(
            route_version="predhistcsv-v1",
            index=idx,
            date=(the_date.isoformat() if the_date else None),
        )
        try:
            hdr_base["X-Expiry-Tag"] = str(expiry_tag or "")
            hdr_base["X-Offset"] = str(offset or "")
            hdr_base["X-Prefix"] = str(prefix or "")
        except (TypeError, ValueError):
            pass

        # Resolve 'now' via live_csv for robust windowing
        eff_tag = normalize_expiry_tag(idx, expiry_tag)
        p_live = find_live_csv((project_root() / "data" / "g6_data"), idx, eff_tag, offset, the_date)
        now_ms: Optional[int] = None
        try:
            if p_live and getattr(p_live, "exists")():
                rows = load_csv_rows_full(p_live)
                if rows:
                    try:
                        now_ms = infer_now_ms_from_rows(rows)
                    except (TypeError, ValueError, KeyError):
                        now_ms = None
        except BaseException as e:
            import asyncio
            if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                raise
            now_ms = None

        arch_file_bands = bands_archive_path(project_root=project_root, index=idx, d=the_date)
        if not arch_file_bands.exists():
            hdr_base["X-Empty-Reason"] = "bands_archive_missing"
            return PlainTextResponse(
                "gen_time_iso,gen_ms,index,target_time_iso,target_ms,horizon_min,q10,q50,q90\n",
                headers=hdr_base,
            )

        # Load rows for requested horizon
        entries: list[tuple[int, int, Optional[float], Optional[float], Optional[float]]] = []
        q10_name = q50_name = q90_name = None
        with arch_file_bands.open("r", encoding="utf-8", newline="") as f:
            rd = csv.DictReader(f)
            qcols = detect_quantile_columns(rd.fieldnames)
            q10_name = qcols.get(10)
            q50_name = qcols.get(50)
            q90_name = qcols.get(90)

        for row in iter_dict_rows(arch_file_bands):
            gen_ms = parse_int(row, "gen_ms") or 0
            tgt_ms = parse_int(row, "target_ms") or 0
            hmin = parse_int(row, "horizon_min") or 0
            if not gen_ms or not tgt_ms or hmin != int(horizon_minutes):
                continue

            q10v = parse_float(row, q10_name) if q10_name else None
            q50v = parse_float(row, q50_name) if q50_name else None
            q90v = parse_float(row, q90_name) if q90_name else None

            # Clamp non-negative
            if isinstance(q10v, (int, float)) and q10v < 0:
                q10v = 0.0
            if isinstance(q50v, (int, float)) and q50v < 0:
                q50v = 0.0
            if isinstance(q90v, (int, float)) and q90v < 0:
                q90v = 0.0

            entries.append((gen_ms, tgt_ms, q10v, q50v, q90v))

        if not entries:
            hdr_base["X-Empty-Reason"] = "no_band_rows"
            return PlainTextResponse(
                "gen_time_iso,gen_ms,index,target_time_iso,target_ms,horizon_min,q10,q50,q90\n",
                headers=hdr_base,
            )

        # Sort and window by generation time
        entries.sort(key=lambda x: x[0])
        if now_ms is None:
            now_ms = entries[-1][0]
        cutoff = int(now_ms) - int(window_minutes) * 60_000
        filtered = [e for e in entries if e[0] >= cutoff]

        # Optional bucketing by gen time: keep last per bucket
        if bucket_ms and bucket_ms > 1_000:
            bucketed: dict[int, tuple[int, int, Optional[float], Optional[float], Optional[float]]] = {}
            for e in filtered:
                b = (e[0] // int(bucket_ms)) * int(bucket_ms)
                bucketed[b] = e
            filtered = [bucketed[k] for k in sorted(bucketed.keys())]

        # Build CSV
        buf = StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "gen_time_iso",
                "gen_ms",
                "index",
                "target_time_iso",
                "target_ms",
                "horizon_min",
                f"{prefix}q10",
                f"{prefix}q50",
                f"{prefix}q90",
            ]
        )
        for gen_ms, tgt_ms, q10v, q50v, q90v in filtered:
            gen_iso = (
                datetime.utcfromtimestamp(int(gen_ms) / 1000.0)
                .replace(microsecond=0)
                .isoformat()
                + "Z"
            )
            tgt_iso = (
                datetime.utcfromtimestamp(int(tgt_ms) / 1000.0)
                .replace(microsecond=0)
                .isoformat()
                + "Z"
            )
            horizon_min = max(0, int(round((int(tgt_ms) - int(gen_ms)) / 60000.0)))
            w.writerow(
                [
                    gen_iso,
                    int(gen_ms),
                    idx,
                    tgt_iso,
                    int(tgt_ms),
                    horizon_min,
                    ("" if q10v is None else q10v),
                    ("" if q50v is None else q50v),
                    ("" if q90v is None else q90v),
                ]
            )

        return PlainTextResponse(buf.getvalue(), headers=hdr_base)

    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
