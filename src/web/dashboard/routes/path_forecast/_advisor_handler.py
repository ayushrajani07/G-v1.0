from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from src.path_forecast.composite import CompositeConfig, CompositePathForecaster
from src.path_forecast.retrieval import RetrievalConfig, RetrievalPathForecaster

from .._index_norm import normalize_index
from .._date_norm import resolve_date
from .._now_norm import build_realized_map_and_times, nearest_time_key, now_and_cutoff

from ._bands_archive import detect_quantile_columns, parse_float, parse_int
from ._archive_paths import bands_archive_path


async def handle_path_advisor(
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
    project_root: Callable[[], object],
    find_live_csv: Callable[..., object],
    load_csv_rows_full: Callable[[object], list[dict]],
    extract_tp: Callable[[dict], object],
    load_calibration: Callable[[str], dict],
) -> JSONResponse:
    """Implementation of /api/ml/path_advisor extracted from router."""

    try:
        import csv

        idx = normalize_index(index)
        the_date = resolve_date(date_str)

        base = project_root() / "data" / "g6_data"
        p_live = find_live_csv(base, idx, expiry_tag, offset, the_date)
        alerts: list[dict] = []
        summary: dict[str, object] = {}

        # Default summary values
        summary.update(
            {
                "coverage": None,
                "target": None,
                "gap": None,
                "samples": 0,
                "band_scale": None,
                "mode": None,
                "fallback": False,
            }
        )

        try:
            if (not p_live) or (not getattr(p_live, "exists")()):
                alerts.append(
                    {
                        "level": "crit",
                        "code": "live_csv_missing",
                        "message": f"live_csv not found for {idx} ({expiry_tag},{offset},{the_date})",
                        "prognosis": "No diagnostics possible; coverage/width unknown.",
                        "remedy": "Verify data feed and file path mapping; check provider ingestion and path resolution.",
                        "metrics": {},
                    }
                )
                return JSONResponse(
                    {
                        "index": idx,
                        "horizon": int(horizon),
                        "window_minutes": int(window_minutes),
                        "date": the_date.isoformat(),
                        "summary": summary,
                        "alerts": alerts,
                    }
                )
        except (AttributeError, TypeError, OSError, ValueError):
            alerts.append(
                {
                    "level": "crit",
                    "code": "live_csv_missing",
                    "message": f"live_csv not found for {idx} ({expiry_tag},{offset},{the_date})",
                    "prognosis": "No diagnostics possible; coverage/width unknown.",
                    "remedy": "Verify data feed and file path mapping; check provider ingestion and path resolution.",
                    "metrics": {},
                }
            )
            return JSONResponse(
                {
                    "index": idx,
                    "horizon": int(horizon),
                    "window_minutes": int(window_minutes),
                    "date": the_date.isoformat(),
                    "summary": summary,
                    "alerts": alerts,
                }
            )

        rows = load_csv_rows_full(p_live)
        if not rows:
            alerts.append(
                {
                    "level": "crit",
                    "code": "no_live_rows",
                    "message": "live_csv has no rows",
                    "prognosis": "Coverage cannot be evaluated until data flows.",
                    "remedy": "Check upstream collector; verify today’s file has content.",
                    "metrics": {},
                }
            )
            return JSONResponse(
                {
                    "index": idx,
                    "horizon": int(horizon),
                    "window_minutes": int(window_minutes),
                    "date": the_date.isoformat(),
                    "summary": summary,
                    "alerts": alerts,
                }
            )

        # realized timestamps (sorted) and map
        realized, ts_sorted = build_realized_map_and_times(
            rows,
            bucket_ms=None,
            tp_getter=lambda r: r.get("tp"),
        )
        if not realized:
            alerts.append(
                {
                    "level": "crit",
                    "code": "no_realized_map",
                    "message": "Could not construct realized map from live_csv",
                    "prognosis": "Coverage evaluation blocked.",
                    "remedy": "Validate column names (ts/time,tp) and data quality.",
                    "metrics": {},
                }
            )
            return JSONResponse(
                {
                    "index": idx,
                    "horizon": int(horizon),
                    "window_minutes": int(window_minutes),
                    "date": the_date.isoformat(),
                    "summary": summary,
                    "alerts": alerts,
                }
            )

        now_ms, _cutoff_ignored = now_and_cutoff(ts_sorted, window_minutes)
        if now_ms is None:
            return JSONResponse(
                {
                    "index": idx,
                    "horizon": int(horizon),
                    "window_minutes": int(window_minutes),
                    "date": the_date.isoformat(),
                    "summary": summary,
                    "alerts": alerts,
                }
            )

        # Calibration snapshot
        cal = load_calibration(idx)
        band_scale = float(cal.get("band_scale", 1.0)) if isinstance(cal.get("band_scale"), (int, float)) else None
        target = float(cal.get("target", 0.8)) if isinstance(cal.get("target"), (int, float)) else 0.8
        cal_actual = cal.get("actual")
        cal_samples = cal.get("samples")
        summary.update({"band_scale": band_scale, "target": target})

        # Coverage and samples using bands archive (calibrated view)
        arch_file_bands = bands_archive_path(project_root=project_root, index=idx, d=the_date)
        cov = None
        samples = 0
        bw_mean = None
        if arch_file_bands.exists():
            tol = max(1, int(bucket_ms) // 2)
            total = 0
            cover = 0
            bw_sum = 0.0
            with arch_file_bands.open("r", encoding="utf-8", newline="") as f:
                rd = csv.DictReader(f)
                qcols = detect_quantile_columns(rd.fieldnames)
                q10_name = qcols.get(10)
                q90_name = qcols.get(90)
                cutoff_gen = now_ms - int(window_minutes) * 60_000
                for row in rd:
                    gen_ms = parse_int(row, "gen_ms") or 0
                    tgt_ms = parse_int(row, "target_ms") or 0
                    hmin = parse_int(row, "horizon_min") or 0
                    if not gen_ms or not tgt_ms or hmin != int(horizon):
                        continue
                    if gen_ms < cutoff_gen or tgt_ms > now_ms:
                        continue
                    if not q10_name or not q90_name:
                        continue
                    q10v = parse_float(row, q10_name)
                    q90v = parse_float(row, q90_name)
                    if q10v is None or q90v is None:
                        continue
                    # NN align
                    best_r = nearest_time_key(ts_sorted, tgt_ms, tol)
                    if best_r is None:
                        continue
                    rv = realized.get(best_r)
                    if rv is None:
                        continue
                    total += 1
                    if q10v <= rv <= q90v:
                        cover += 1
                    bw_sum += float(q90v) - float(q10v)
            samples = total
            cov = (cover / float(total)) if total > 0 else None
            bw_mean = (bw_sum / float(total)) if total > 0 else None
        else:
            alerts.append(
                {
                    "level": "warn",
                    "code": "no_bands_archive",
                    "message": "Bands archive for today not found; stats may be blank early in session.",
                    "prognosis": "Coverage will populate once bands start archiving.",
                    "remedy": "Ensure ribbon endpoint is being queried (it archives bands) and archiver is running.",
                    "metrics": {"file": str(arch_file_bands)},
                }
            )

        summary.update({"coverage": cov, "samples": samples})

        # Build alerts based on thresholds
        # 1) Low samples
        if samples <= int(min_samples_crit):
            alerts.append(
                {
                    "level": "crit",
                    "code": "low_samples",
                    "message": f"Only {samples} samples in window {window_minutes}m for H={horizon}m.",
                    "prognosis": "Coverage estimate is unstable; decisions may be noisy.",
                    "remedy": "Wait for more data, widen diagnostics window, or verify bands archive is updating.",
                    "metrics": {"samples": samples, "window_minutes": window_minutes},
                }
            )
        elif samples <= int(min_samples_warn):
            alerts.append(
                {
                    "level": "warn",
                    "code": "low_samples",
                    "message": f"Low samples: {samples} in {window_minutes}m for H={horizon}m.",
                    "prognosis": "Coverage confidence is limited until more points accumulate.",
                    "remedy": "Consider widening diag_window or revisit bands archiving cadence.",
                    "metrics": {"samples": samples, "window_minutes": window_minutes},
                }
            )

        # 2) Coverage gap vs target
        if cov is not None and isinstance(target, (int, float)):
            gap = float(cov) - float(target)
            summary["gap"] = gap
            try:
                summary["gap_abs"] = abs(gap)
            except TypeError:
                pass
            gabs = abs(gap)
            if gabs >= float(gap_crit) and samples > 0:
                alerts.append(
                    {
                        "level": "crit",
                        "code": "coverage_gap",
                        "message": f"Coverage gap {gap:+.2f} (cov={cov:.2f}, target={target:.2f}).",
                        "prognosis": "Bands are materially mis-scaled; realized values falling outside expected range.",
                        "remedy": "Re-run calibration with sufficient window or adjust band_scale smoothing caps.",
                        "metrics": {"coverage": cov, "target": target, "gap": gap},
                    }
                )
            elif gabs >= float(gap_warn) and samples > 0:
                alerts.append(
                    {
                        "level": "warn",
                        "code": "coverage_gap",
                        "message": f"Coverage gap {gap:+.2f} (cov={cov:.2f}, target={target:.2f}).",
                        "prognosis": "Moderate miscalibration likely; monitor if trend persists.",
                        "remedy": "Consider a gentle calibration update or broaden lookback.",
                        "metrics": {"coverage": cov, "target": target, "gap": gap},
                    }
                )

        # 3) Calibration saturation (at or near caps)
        if isinstance(band_scale, (int, float)):
            if band_scale >= 4.9:
                alerts.append(
                    {
                        "level": "warn",
                        "code": "scale_high_saturation",
                        "message": f"band_scale={band_scale:.2f} near upper cap (5.0).",
                        "prognosis": "Calibration may be maxed out; persistent undercoverage expected without broader changes.",
                        "remedy": "Review target, widen bands in prior, or expand features/retrieval.",
                        "metrics": {"band_scale": band_scale},
                    }
                )
            elif band_scale <= 0.55:
                alerts.append(
                    {
                        "level": "warn",
                        "code": "scale_low_saturation",
                        "message": f"band_scale={band_scale:.2f} near lower cap (0.5).",
                        "prognosis": "Calibration may be constrained; persistent overcoverage expected.",
                        "remedy": "Review target or narrow prior bands; consider shrinking retrieval dispersion.",
                        "metrics": {"band_scale": band_scale},
                    }
                )

        # 4) Retrieval/meta advisories + staleness
        # Build a minimal meta similar to path_forecast_meta to get mode and retrieval candidates
        try:
            # Determine now_ms from last live row
            now_ms_row = ts_sorted[-1]
            # Use composite for richer meta if available
            recent_tp: list[list[float]] = []
            for r in rows[-120:]:
                tpv = extract_tp(r)
                if isinstance(tpv, (int, float)):
                    recent_tp.append([float(tpv)])
            mode_used = "retrieval"
            retrieval_meta: dict[str, object] = {}
            try:
                ccfg = CompositeConfig(
                    root=project_root() / "data" / "g6_data",
                    expiry_tag=expiry_tag,
                    offset=offset,
                    window=60,
                    k=15,
                )
                comp = CompositePathForecaster(ccfg)
                comp.forecast_path(
                    recent_tp,
                    context={"index": idx, "now_ms": now_ms_row, "live_rows": rows},
                    quantiles=(0.5,),
                    horizon_minutes=int(horizon),
                    bucket_ms=int(bucket_ms),
                )
                retrieval_meta = dict(comp.last_meta or {})
                mode_used = "hybrid"
            except (AttributeError, TypeError, ValueError, OSError, RuntimeError):
                try:
                    rcfg = RetrievalConfig(
                        root=project_root() / "data" / "g6_data",
                        expiry_tag=expiry_tag,
                        offset=offset,
                        window=60,
                        k=15,
                    )
                    retr = RetrievalPathForecaster(rcfg)
                    retr.forecast_path(
                        recent_tp,
                        context={"index": idx, "now_ms": now_ms_row, "live_rows": rows},
                        quantiles=(0.5,),
                        horizon_minutes=int(horizon),
                        bucket_ms=int(bucket_ms),
                    )
                    retrieval_meta = dict(retr.last_meta or {})
                    mode_used = "retrieval"
                except (AttributeError, TypeError, ValueError, OSError, RuntimeError):
                    mode_used = "fallback"
                    retrieval_meta = {}

            # Candidates/K threshold
            try:
                def _safe_int(x, d=0):
                    try:
                        return int(float(f"{x}"))
                    except (TypeError, ValueError, OverflowError):
                        return int(d)
                cand = _safe_int(retrieval_meta.get("candidates_total", 0), 0)
                need = _safe_int(retrieval_meta.get("threshold_needed", 0), 0)
                k_used = _safe_int(retrieval_meta.get("k_used", 0), 0)
                if cand and need and cand < need:
                    alerts.append(
                        {
                            "level": "warn",
                            "code": "retrieval_low_candidates",
                            "message": f"Retrieval candidates low: {cand} < needed {need} (k_used={k_used}).",
                            "prognosis": "Weaker matching; dispersion and bias may worsen.",
                            "remedy": "Broaden window/days, relax filters, or ensure historical corpus is complete.",
                            "metrics": {
                                "candidates_total": cand,
                                "threshold_needed": need,
                                "k_used": k_used,
                            },
                        }
                    )
            except (AttributeError, TypeError, ValueError, KeyError):
                pass

            # Mode fallback
            summary["mode"] = mode_used
            if mode_used == "fallback":
                alerts.append(
                    {
                        "level": "crit",
                        "code": "forecast_fallback_mode",
                        "message": "Forecast operating in fallback mode.",
                        "prognosis": "Ribbon quality degraded; uncertainty not informed by retrieval/priors.",
                        "remedy": "Inspect retrieval data availability and prior computation path.",
                        "metrics": {},
                    }
                )
                summary["fallback"] = True

            # Staleness check using meta gen vs last live row
            try:
                gen_ms = int(now_ms_row)
                staleness_ms = max(0, (int(ts_sorted[-1]) - int(gen_ms)))
                if staleness_ms > 2 * 60_000:
                    alerts.append(
                        {
                            "level": "warn",
                            "code": "stale_generation",
                            "message": f"Generation reference appears stale by ~{staleness_ms//1000}s.",
                            "prognosis": "Panels may be lagging; coverage/width stale relative to latest tick.",
                            "remedy": "Ensure ribbon panel is refreshing and API cache TTL is appropriate.",
                            "metrics": {"staleness_ms": staleness_ms},
                        }
                    )
            except (TypeError, ValueError, IndexError, OverflowError):
                pass
        except (AttributeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

        # overall level (crit if any, else warn if any, else ok)
        overall = "ok"
        for a in alerts:
            if a.get("level") == "crit":
                overall = "crit"
                break
            if a.get("level") == "warn":
                overall = "warn"
        summary["level"] = overall

        return JSONResponse(
            {
                "index": idx,
                "horizon": int(horizon),
                "window_minutes": int(window_minutes),
                "date": the_date.isoformat(),
                "summary": summary,
                "alerts": alerts,
                "metrics": {
                    "coverage": cov,
                    "samples": samples,
                    "band_width_mean": bw_mean,
                    "band_scale": band_scale,
                    "cal_actual": cal_actual,
                    "cal_samples": cal_samples,
                },
            }
        )

    except BaseException as e:
        import asyncio

        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
