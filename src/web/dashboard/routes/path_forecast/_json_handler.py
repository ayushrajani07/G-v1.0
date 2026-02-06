from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .._index_norm import normalize_index

from ._archive import _apply_calibration_and_archive
from ._json_ribbon import _build_output_rows_and_headers
from ._pipeline import _run_forecast_pipeline
from ._profiles import _apply_profile_overrides
from ._qmap import (
    _cap_to_close,
    _inject_degenerate_dispersion,
    _inject_fallback_trend,
    _recentering_shift,
    _sanitize_qmap,
)
from ._api_contract import base_headers

logger = logging.getLogger(__name__)


async def handle_path_forecast_json(
    *,
    request: Request,
    index: str,
    horizon_minutes: int,
    expiry_tag: str,
    offset: str,
    window: int,
    k: int,
    mode: str,
    bucket_ms: int,
    date_str: Optional[str],
    calibrate: bool,
    no_cache: bool,
    align: str,
    profile: Optional[str],
    distance_metric: Optional[str],
    weight_mode: Optional[str],
    recent_gamma: Optional[float],
    regime_tolerance: Optional[float],
    regime_penalty: Optional[float],
    now_override_ms: Optional[str],
    use_ann: Optional[bool],
    ann_space: Optional[str],
    ann_max_candidates: Optional[int],
    # Dependencies injected from router for test hook compatibility
    load_live_rows_and_context: Callable[..., Any],
    load_calibration: Callable[[str], dict],
    apply_band_scale: Callable[[dict, float], dict],
    cache_get: Callable[[str, str, int], Optional[dict]],
    cache_set: Callable[[str, str, dict], None],
    cache_ttl_ms: int,
) -> JSONResponse:
    """Implementation of /api/ml/path_forecast_json extracted from the router.

    The router passes in a few dependencies so existing monkeypatch-based tests keep
    working (notably project_root- and package-level hook behavior).
    """

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

        hdr_base = base_headers(
            route_version="json-v3",
            index=idx_norm,
            date=(the_date.isoformat() if the_date else None),
        )
        try:
            hdr_base["X-Expiry-Tag"] = str(eff_tag or "")
            hdr_base["X-Offset"] = str(offset or "")
        except (TypeError, ValueError):
            pass

        if rows is None:
            try:
                logger.info("path_forecast: empty-return rows_none index=%s horizon=%s", idx_norm, horizon_minutes)
            except (TypeError, ValueError):
                pass
            hdr_base["X-Empty-Reason"] = "live_csv_not_found"
            return JSONResponse([], headers=hdr_base)

        if (not rows) or last_tp is None or ref_now_ms is None:
            try:
                logger.info(
                    "path_forecast: empty-return rows_len=%s last_tp=%s ref_now_ms=%s index=%s horizon=%s",
                    (len(rows) if rows else 0),
                    last_tp,
                    ref_now_ms,
                    idx_norm,
                    horizon_minutes,
                )
            except (TypeError, ValueError):
                pass
            hdr_base["X-Empty-Reason"] = "no_live_rows"
            return JSONResponse([], headers=hdr_base)

        # Effective knobs via profile
        (
            window_eff,
            k_eff,
            mode_eff,
            fb_band_pct,
            distance_metric_eff,
            weight_mode_eff,
            recent_gamma_eff,
            regime_tolerance_eff,
            regime_penalty_eff,
            ann_use_eff,
            ann_space_eff,
            ann_max_cand_eff,
            pdiag,
        ) = _apply_profile_overrides(
            profile,
            window,
            k,
            mode,
            distance_metric,
            weight_mode,
            recent_gamma,
            regime_tolerance,
            regime_penalty,
            ref_now_ms,
            use_ann=use_ann,
            ann_space=ann_space,
            ann_max_candidates=ann_max_candidates,
        )

        bucket_key = (ref_now_ms // int(bucket_ms)) * int(bucket_ms)
        cache_key = f"json|{idx_norm}|{eff_tag}|{offset}|{window_eff}|{k_eff}|{horizon_minutes}|{int(bucket_ms)}|{mode_eff}|{profile or ''}|{bucket_key}"

        times: list[int] = []
        qmap: dict = {}
        mode_used = ""
        diag: dict[str, object] = {}

        if not no_cache:
            c = cache_get("path_forecast_json", cache_key, cache_ttl_ms)
            if c and c.get("bucket") == bucket_key:
                times = c.get("times") or []
                qmap = c.get("qmap") or {}
                mode_used = c.get("mode") or ""
                diag = c.get("diag") or {}

                # If cached bands are degenerate, apply dispersion in-place so panels don't freeze
                try:
                    q10_c = list(qmap.get(0.1) or qmap.get("0.1") or [])
                    q50_c = list(qmap.get(0.5) or qmap.get("0.5") or [])
                    q90_c = list(qmap.get(0.9) or qmap.get("0.9") or [])
                    total_c = min(len(q10_c), len(q50_c), len(q90_c))
                    identical_c = (
                        total_c > 0
                        and len(q10_c) == len(q50_c) == len(q90_c)
                        and q10_c == q50_c == q90_c
                    )
                    flat_cnt_c = 0
                    if total_c >= 10:
                        for i in range(total_c):
                            v10 = q10_c[i]
                            v50v = q50_c[i]
                            v90 = q90_c[i]
                            if all(isinstance(v, (int, float)) for v in (v10, v50v, v90)) and v10 == v50v == v90:
                                flat_cnt_c += 1
                    flat_share_c = (flat_cnt_c / float(total_c)) if total_c > 0 else 0.0
                    if identical_c or flat_share_c >= 0.8 or bool(diag.get("fallback_stub")):
                        try:
                            _inject_degenerate_dispersion(idx_norm, int(horizon_minutes), times, qmap, diag)
                            diag["ribbon_pre_disp"] = 1
                        except (AttributeError, KeyError, TypeError, ValueError):
                            pass
                        # If injection didn't mark pre-disp, force a minimal widening so panels show variance
                        try:
                            if not diag.get("ribbon_pre_disp"):
                                q10_for = list(qmap.get(0.1) or qmap.get("0.1") or [])
                                q50_for = list(qmap.get(0.5) or qmap.get("0.5") or [])
                                q90_for = list(qmap.get(0.9) or qmap.get("0.9") or [])
                                total_for = min(len(q10_for), len(q50_for), len(q90_for))
                                if total_for > 0:
                                    base_pct_for = 0.01
                                    for i in range(total_for):
                                        v50f = q50_for[i]
                                        if isinstance(v50f, (int, float)):
                                            spreadf = max(0.0001, base_pct_for * float(v50f))
                                            if i < len(q10_for):
                                                q10_for[i] = max(0.0, float(v50f) - spreadf)
                                            if i < len(q90_for):
                                                q90_for[i] = float(v50f) + spreadf
                                    qmap[0.1] = q10_for
                                    qmap["0.1"] = q10_for
                                    qmap[0.5] = q50_for
                                    qmap["0.5"] = q50_for
                                    qmap[0.9] = q90_for
                                    qmap["0.9"] = q90_for
                                    diag["ribbon_pre_disp"] = 1
                        except (AttributeError, KeyError, TypeError, ValueError):
                            pass
                except (AttributeError, KeyError, TypeError, ValueError):
                    pass

        if not times:
            qs = [0.1, 0.5, 0.9]
            times, qmap, mode_used, diag = _run_forecast_pipeline(
                idx_norm,
                rows,
                ref_now_ms,
                horizon_minutes,
                bucket_ms,
                mode_eff,
                fb_band_pct,
                window_eff,
                k_eff,
                distance_metric_eff,
                weight_mode_eff,
                recent_gamma_eff,
                regime_tolerance_eff,
                regime_penalty_eff,
                qs,
                use_ann=ann_use_eff,
                ann_space=ann_space_eff,
                ann_max_candidates=ann_max_cand_eff,
            )

            # Defensive: sanitize qmap to eliminate None entries that can trigger float(None)
            try:
                qmap = _sanitize_qmap(qmap)  # type: ignore[arg-type]
            except (AttributeError, TypeError, ValueError):
                pass

            if mode_used == "fallback":
                _inject_fallback_trend(rows, times, ref_now_ms, qmap, diag)

            # Apply profile overrides post-computation
            try:
                diag.update(pdiag)
                diag["mode_eff"] = mode_eff
            except (AttributeError, TypeError, ValueError):
                pass

            try:
                cache_set(
                    "path_forecast_json",
                    cache_key,
                    {
                        "bucket": bucket_key,
                        "times": times,
                        "qmap": qmap,
                        "mode": mode_used,
                        "diag": diag,
                    },
                )
            except (TypeError, ValueError):
                pass

            # Pre-cache dispersion enforcement
            pre_disp_applied = False
            try:
                q10_c = list(qmap.get(0.1) or qmap.get("0.1") or [])
                q50_c = list(qmap.get(0.5) or qmap.get("0.5") or [])
                q90_c = list(qmap.get(0.9) or qmap.get("0.9") or [])
                total_c = min(len(q10_c), len(q50_c), len(q90_c))
                identical_c = (
                    total_c > 0
                    and len(q10_c) == len(q50_c) == len(q90_c)
                    and q10_c == q50_c == q90_c
                )
                flat_cnt_c = 0
                if total_c >= 10:
                    for i in range(total_c):
                        v10 = q10_c[i]
                        v50v = q50_c[i]
                        v90 = q90_c[i]
                        if all(isinstance(v, (int, float)) for v in (v10, v50v, v90)) and v10 == v50v == v90:
                            flat_cnt_c += 1
                flat_share_c = (flat_cnt_c / float(total_c)) if total_c > 0 else 0.0
                if identical_c or flat_share_c >= 0.8 or bool(diag.get("fallback_stub")):
                    try:
                        _inject_degenerate_dispersion(idx_norm, int(horizon_minutes), times, qmap, diag)
                        pre_disp_applied = True
                        diag["ribbon_pre_disp"] = 1
                    except (AttributeError, KeyError, TypeError, ValueError):
                        pre_disp_applied = False
            except (AttributeError, KeyError, TypeError, ValueError):
                pre_disp_applied = False

            # Avoid caching collapsed stub
            try:
                if bool(diag.get("fallback_stub")) and pre_disp_applied:
                    try:
                        cache_set(
                            "path_forecast_json",
                            cache_key,
                            {"bucket": bucket_key, "times": [], "qmap": {}, "mode": "", "diag": {}},
                        )
                    except (TypeError, ValueError):
                        pass
            except (AttributeError, TypeError, ValueError):
                pass

        # Hard cap beyond market close
        _cap_to_close(times, qmap, ref_now_ms)
        try:
            if not times:
                logger.info(
                    "path_forecast: post-cap empty times index=%s horizon=%s ref_now_ms=%s",
                    idx_norm,
                    horizon_minutes,
                    ref_now_ms,
                )
        except (TypeError, ValueError):
            pass

        # Recentering and calibration + archival
        try:
            _recentering_shift(times, qmap, float(last_tp), diag)
        except (AttributeError, KeyError, TypeError, ValueError):
            pass

        try:
            if calibrate:
                cal = load_calibration(idx_norm)
                _bs_raw = cal.get("band_scale", 1.0)
                band_scale_eff = float(_bs_raw) if isinstance(_bs_raw, (int, float)) else 1.0
                qmap = apply_band_scale(qmap, band_scale_eff)
        except (AttributeError, KeyError, TypeError, ValueError):
            pass

        # Post-calibration safety: re-inject dispersion if bands collapsed
        try:
            _inject_degenerate_dispersion(idx_norm, int(horizon_minutes), times, qmap, diag)
        except (AttributeError, KeyError, TypeError, ValueError):
            pass

        _apply_calibration_and_archive(
            idx_norm,
            ref_now_ms,
            rows,
            times,
            qmap,
            diag,
            profile,
            mode_used,
            int(bucket_ms),
        )

        # Compact metrics log (best-effort)
        try:
            logger.info(
                "path_forecast: %s mode=%s k=%s win=%s cand=%s pruned=%s retained=%s cache[h=%s m=%s e=%s]",
                idx_norm,
                (mode_used or ""),
                str(diag.get("k_used", "")),
                str(diag.get("window_used", "")),
                str(diag.get("candidates_total", "")),
                str(diag.get("pruned_days", "")),
                str(diag.get("retained_days", "")),
                str(diag.get("cache_hits", "")),
                str(diag.get("cache_misses", "")),
                str(diag.get("cache_evictions", "")),
            )
        except (TypeError, ValueError):
            pass

        out, headers = _build_output_rows_and_headers(
            idx_norm,
            rows,
            times,
            qmap,
            diag,
            float(last_tp),
            ref_now_ms,
            int(bucket_ms),
            align,
            mode_used,
            profile,
            distance_metric_eff,
            weight_mode_eff,
            recent_gamma_eff,
            regime_tolerance_eff,
            regime_penalty_eff,
        )

        try:
            if not out:
                logger.info(
                    "path_forecast: final empty out index=%s horizon=%s times_len=%s",
                    idx_norm,
                    horizon_minutes,
                    len(times),
                )
        except (TypeError, ValueError):
            pass

        return JSONResponse(out, headers=headers)

    except HTTPException:
        raise
    except BaseException as e:
        import asyncio

        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
