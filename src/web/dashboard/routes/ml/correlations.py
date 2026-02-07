from __future__ import annotations

import asyncio
import datetime as _dt
from typing import Optional

from fastapi import HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...core.csv_io import load_csv_rows_full as _load_csv_rows_full
from .._index_norm import normalize_index
from ._common import project_root as _project_root, resolve_live_csv_path as _resolve_live_csv_path
async def api_ml_correlations(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    expiry_tag: str = Query("this_month", description="Expiry tag for live_csv lookup"),
    offset: str = Query("0", description="Offset for live_csv lookup"),
    window_minutes: int = Query(120, ge=1, le=24 * 60, description="Lookback window in minutes"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Bucket size for time alignment in ms"),
    set_name: str = Query("set1", description="Which predefined set to use: set1, set2, or 'all'"),
    set_param: Optional[str] = Query(None, description="Deprecated: use set_name", alias="set"),
    cols: Optional[str] = Query(None, description="Comma-separated explicit column list to use"),
    method: str = Query("pearson", description="Correlation method (currently pearson only)"),
    format: str = Query("long", description="Output format: 'long' (tidy) or 'wide' (matrix)"),
) -> PlainTextResponse:
    """Return correlation matrix for selected columns from live_csv over a window.

    Predefined sets:
      - set1: index_price, ce_vol, pe_vol, ce_oi, pe_oi, ce_iv, pe_iv, tp
      - set2: set1 + ce_delta, pe_delta, ce_theta, pe_theta, ce_vega, pe_vega, ce_gamma, pe_gamma, ce_rho, pe_rho, tp_net_change, tp_day_change

    Output (long): col_i,col_j,correlation,count,window_minutes
    Output (wide): first row is header with column names; cells are correlation values
    """
    try:
        idx_norm = normalize_index(index)

        from datetime import date

        p = _resolve_live_csv_path(idx_norm, expiry_tag, offset, date.today())
        if not p or not p.exists():
            raise HTTPException(status_code=404, detail="live_csv file not found")
        rows = _load_csv_rows_full(p)

        now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
        cutoff_ms = now_ms - window_minutes * 60_000

        set1 = [
            "index_price",
            "ce_vol",
            "pe_vol",
            "ce_oi",
            "pe_oi",
            "ce_iv",
            "pe_iv",
            "tp",
        ]
        set2 = set1 + [
            "ce_delta",
            "pe_delta",
            "ce_theta",
            "pe_theta",
            "ce_vega",
            "pe_vega",
            "ce_gamma",
            "pe_gamma",
            "ce_rho",
            "pe_rho",
            "tp_net_change",
            "tp_day_change",
        ]

        chosen = (set_name or "").strip() or (set_param or "").strip() or "set1"
        if cols:
            use_cols = [c.strip() for c in cols.split(",") if c.strip()]
        else:
            if chosen.lower() == "set2":
                use_cols = set2
            elif chosen.lower() == "all":
                keys: set[str] = set()
                for r in rows[:200]:
                    if isinstance(r, dict):
                        keys.update((str(k) for k in r.keys()))
                use_cols = sorted([k for k in keys if k not in {"time", "ts", "time_str", "time_epoch_s"}])
            else:
                use_cols = set1

        buckets: dict[int, dict[str, float]] = {}
        day_open_tp: Optional[float] = None
        last_tp: Optional[float] = None
        for r in rows:
            try:
                ems = int(r.get("ts") or r.get("time") or 0)
            except (TypeError, ValueError):
                continue
            if not ems or ems < cutoff_ms:
                continue
            bucket = (ems // bucket_ms) * bucket_ms
            rec = buckets.get(bucket)
            if rec is None:
                rec = {}
                buckets[bucket] = rec
            for c in use_cols:
                v = r.get(c)
                if isinstance(v, (int, float)):
                    rec[c] = float(v)
            tp = r.get("tp")
            if isinstance(tp, (int, float)):
                tp_f = float(tp)
                if last_tp is not None:
                    rec.setdefault("tp_net_change", tp_f - last_tp)
                last_tp = tp_f
                if day_open_tp is None:
                    day_open_tp = tp_f
                rec.setdefault("tp_day_change", tp_f - (day_open_tp or tp_f))

        keys = sorted(buckets.keys())
        if not keys:
            return PlainTextResponse("col_i,col_j,correlation,count,window_minutes\n", media_type="text/csv")

        present_cols: list[str] = []
        for c in use_cols:
            if any(c in buckets[k] for k in keys):
                present_cols.append(c)

        series: dict[str, list[float]] = {c: [] for c in present_cols}
        counts: dict[str, int] = {c: 0 for c in present_cols}
        for k in keys:
            rec = buckets[k]
            for c in present_cols:
                if c in rec and isinstance(rec[c], (int, float)):
                    series[c].append(float(rec[c]))
                    counts[c] += 1
                else:
                    series[c].append(float("nan"))

        def _pair_corr(xs: list[float], ys: list[float]) -> tuple[float, int]:
            try:
                import math

                pairs = [(x, y) for x, y in zip(xs, ys) if (x == x) and (y == y)]
                n = len(pairs)
                if n < 3:
                    return float("nan"), n
                mean_x = sum(x for x, _ in pairs) / n
                mean_y = sum(y for _, y in pairs) / n
                cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / (n - 1)
                var_x = sum((x - mean_x) ** 2 for x, _ in pairs) / (n - 1)
                var_y = sum((y - mean_y) ** 2 for _, y in pairs) / (n - 1)
                if var_x <= 0 or var_y <= 0:
                    return float("nan"), n
                return cov / math.sqrt(var_x * var_y), n
            except (ImportError, OverflowError, ZeroDivisionError, TypeError, ValueError):
                return float("nan"), 0

        cols_eff = present_cols
        if format.lower() == "wide":
            out = [",".join(["col", *cols_eff])]
            for i, ci in enumerate(cols_eff):
                row_vals = [ci]
                xi = series[ci]
                for j, cj in enumerate(cols_eff):
                    xj = series[cj]
                    if i == j:
                        row_vals.append("1.0")
                    else:
                        r, _n = _pair_corr(xi, xj)
                        row_vals.append(f"{r:.4f}" if (r == r) else "")
                out.append(",".join(row_vals))
            return PlainTextResponse("\n".join(out), media_type="text/csv")

        out = ["col_i,col_j,correlation,count,window_minutes"]
        for i, ci in enumerate(cols_eff):
            for j in range(i, len(cols_eff)):
                cj = cols_eff[j]
                if ci == cj:
                    out.append(f"{ci},{cj},1.0,{counts[ci]},{window_minutes}")
                else:
                    r, n = _pair_corr(series[ci], series[cj])
                    out.append(f"{ci},{cj},{(f'{r:.4f}' if (r == r) else '')},{n},{window_minutes}")
        return PlainTextResponse("\n".join(out), media_type="text/csv")

    except HTTPException:
        raise
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
