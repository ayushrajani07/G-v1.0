from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse


async def handle_reset_defaults(
    *,
    request: Request,
    uid: str,
    slug: str,
    index: str,
    expiry_tag: str,
    offset: str,
    horizon: Optional[int],
    # injected deps
    normalize_index: Callable[[str], str],
) -> RedirectResponse:
    """Implementation of /api/ml/reset_defaults extracted from router."""

    try:
        idx = normalize_index(index)

        # Per-index presets (extendable to include expiry_tag/offset specific rules)
        if idx in {"BANKNIFTY"}:
            win = 60
        elif idx in {"NIFTY", "SENSEX"}:
            win = 180
        else:
            win = 180

        # Stable defaults for other settings
        k = 20
        mode = "auto"
        bucket = 60_000
        align = "future"
        calibrate = "true"
        diag_window = 180
        hist_minutes = 240
        cal_target = 0.8
        gap_warn = 0.05
        gap_crit = 0.10
        min_samples_warn = 30
        min_samples_crit = 10

        # Keep current time range simple: last 2h
        # Note: we intentionally do not alter index/expiry_tag/offset/horizon
        h = int(horizon) if isinstance(horizon, int) else None
        h_q = f"&var-horizon={h}" if h is not None else ""

        # Base URL for local API (can be made configurable if needed)
        base_url = "http://127.0.0.1:9500"

        # Compose redirect URL back to Grafana dashboard
        dash = f"/d/{uid}/{slug}?from=now-2h&to=now"
        params = (
            f"&var-base_url={base_url}"
            f"&var-index={idx}"
            f"&var-expiry_tag={expiry_tag}"
            f"&var-offset={offset}"
            f"{h_q}"
            f"&var-pf_mode={mode}"
            f"&var-pf_window={win}"
            f"&var-pf_k={k}"
            f"&var-pf_bucket={bucket}"
            f"&var-pf_align={align}"
            f"&var-calibrate={calibrate}"
            f"&var-date_str="
            f"&var-now_ms=${{__to}}"
            f"&var-diag_window={diag_window}"
            f"&var-hist_minutes={hist_minutes}"
            f"&var-cal_target={cal_target}"
            f"&var-gap_warn={gap_warn}"
            f"&var-gap_crit={gap_crit}"
            f"&var-min_samples_warn={min_samples_warn}"
            f"&var-min_samples_crit={min_samples_crit}"
        )
        final_url = dash + params
        return RedirectResponse(url=final_url, status_code=302)

    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
