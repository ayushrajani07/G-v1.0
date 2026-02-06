from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ._api_contract import base_headers, error_payload


async def handle_path_forecast_meta(
    *,
    request: Request,
    index: str,
    expiry_tag: str,
    offset: str,
    window: int,
    k: int,
    horizon_minutes: int,
    bucket_ms: int,
    date_str: Optional[str],
    now_override_ms: Optional[str],
    profile: Optional[str],
    use_ann: Optional[bool],
    ann_space: Optional[str],
    ann_max_candidates: Optional[int],
    # injected deps
    normalize_index: Callable[[str], str],
    load_live_rows_and_context: Callable[..., object],
    apply_profile_overrides: Callable[..., tuple],
    run_forecast_pipeline: Callable[..., tuple],
    sanitize_qmap: Callable[[object], object],
    load_calibration: Callable[[str], dict],
    dt_module,
) -> JSONResponse:
    """Implementation of /api/ml/path_forecast_meta extracted from router."""

    try:
        idx_norm = normalize_index(index)

        rows, last_tp, ref_now_ms, eff_tag, the_date = load_live_rows_and_context(
            request,
            idx_norm,
            expiry_tag,
            offset,
            date_str,
            now_override_ms,
        )

        requested_day = the_date.isoformat() if the_date else None
        hdr_base = base_headers(route_version="meta-v1", index=idx_norm, date=requested_day)
        try:
            hdr_base["X-Expiry-Tag"] = str(eff_tag or "")
            hdr_base["X-Offset"] = str(offset or "")
            hdr_base["X-Gen-Ms"] = str(ref_now_ms or "")
            hdr_base["X-Gen-Iso"] = (
                dt_module.datetime.fromtimestamp(ref_now_ms / 1000).replace(microsecond=0).isoformat()
                if ref_now_ms
                else ""
            )
        except (TypeError, ValueError, AttributeError):
            pass

        if rows is None:
            return JSONResponse(
                error_payload(
                    error="live_csv file not found",
                    index=idx_norm,
                    expiry_tag=eff_tag,
                    offset=offset,
                    date=requested_day,
                ),
                status_code=404,
                headers=hdr_base,
            )

        if (not rows) or last_tp is None or ref_now_ms is None:
            hdr_base["X-Empty-Reason"] = "no_live_rows"
            return JSONResponse(
                error_payload(
                    error="no live rows",
                    index=idx_norm,
                    expiry_tag=eff_tag,
                    offset=offset,
                    date=requested_day,
                    mode="fallback",
                    reason="no live rows",
                ),
                headers=hdr_base,
            )
        source_day = rows[0].get("_day") if isinstance(rows[0], dict) and rows else None
        source_status = "live"

        # Effective profile/window; meta endpoint ignores query runtime knobs and uses profile values only
        (
            window_eff,
            k_eff,
            mode_eff,
            fb_band_pct,
            dist_eff,
            weight_eff,
            recent_gamma_eff,
            regime_tol_eff,
            regime_penalty_eff,
            ann_use_eff,
            ann_space_eff,
            ann_max_cand_eff,
            pdiag,
        ) = apply_profile_overrides(
            profile,
            window,
            k,
            "auto",
            None,
            None,
            None,
            None,
            None,
            ref_now_ms,
            use_ann=use_ann,
            ann_space=ann_space,
            ann_max_candidates=ann_max_candidates,
        )

        # Run minimal forecast (q50 only) for meta diagnostics
        qs = [0.5]
        times, qmap, mode_used, diag = run_forecast_pipeline(
            idx_norm,
            rows,
            ref_now_ms,
            horizon_minutes,
            bucket_ms,
            mode_eff,
            fb_band_pct,
            window_eff,
            k_eff,
            dist_eff,
            weight_eff,
            recent_gamma_eff,
            regime_tol_eff,
            regime_penalty_eff,
            qs,
            use_ann=ann_use_eff,
            ann_space=ann_space_eff,
            ann_max_candidates=ann_max_cand_eff,
        )

        # Sanitize qmap for meta route as well (defensive for synthetic tests)
        try:
            qmap = sanitize_qmap(qmap)
        except BaseException as e:
            import asyncio
            if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                raise
            pass

        try:
            diag.update(pdiag)
        except (AttributeError, TypeError, ValueError):
            pass

        cal = load_calibration(idx_norm)
        _bs_raw = cal.get("band_scale", 1.0)
        band_scale_eff = float(_bs_raw) if isinstance(_bs_raw, (int, float)) else 1.0

        return JSONResponse(
            {
                "mode": mode_used,
                "index": idx_norm,
                "expiry_tag": eff_tag,
                "offset": offset,
                "window": window_eff,
                "k": k_eff,
                "horizon_minutes": horizon_minutes,
                "retrieval": dict(diag),
                "gen_ms": ref_now_ms,
                "last_tp": (float(last_tp) if isinstance(last_tp, (int, float)) else None),
                "last_tp_ms": int(ref_now_ms),
                "last_tp_iso": dt_module.datetime.fromtimestamp(ref_now_ms / 1000)
                .replace(microsecond=0)
                .isoformat(),
                "gen_iso": dt_module.datetime.fromtimestamp(ref_now_ms / 1000)
                .replace(microsecond=0)
                .isoformat(),
                "band_scale": band_scale_eff,
                "cal_target": cal.get("target"),
                "cal_actual": cal.get("actual"),
                "cal_samples": cal.get("samples"),
                "cal_updated_at": cal.get("updated_at"),
                "requested_day": requested_day,
                "source_day": source_day,
                "source_status": source_status,
                "profile": (profile.lower() if isinstance(profile, str) else None),
                "profile_fallback_band_pct": fb_band_pct,
                "profile_force_mode": (mode_eff if profile else None),
                "profile_distance_metric": (dist_eff if profile else None),
                "profile_weight_mode": (weight_eff if profile else None),
                "profile_recent_gamma": (recent_gamma_eff if profile else None),
                "profile_regime_tolerance": (regime_tol_eff if profile else None),
                "profile_regime_penalty": (regime_penalty_eff if profile else None),
            },
            headers=hdr_base,
        )

    except HTTPException:
        raise
    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
