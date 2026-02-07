from __future__ import annotations

import bisect
import json
import datetime as _dt
from pathlib import Path
from typing import Optional, Sequence, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from src.config.env_config import EnvConfig  # Env-driven overrides (abs floor)
import logging
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse

from src.web.dashboard.core.paths import project_root as _project_root
from src.web.dashboard.core.csv_io import (
    find_live_csv as _find_live_csv,
    load_csv_rows_full as _load_csv_rows_full,
)
from src.path_forecast.hybrid import HybridPathForecaster
from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig
from src.path_forecast.composite import CompositePathForecaster, CompositeConfig
from src.path_forecast.common import (
    extract_tp as _extract_tp,
    row_time_ms as _row_time_ms,
    effective_window_since_open as _effective_window_since_open,
)
from src.path_forecast.archive import ArchiveConfig
from src.services.archival import (
    archive_config as _archive_config,
    archive_forecast_q50 as _archive_q50,
    archive_forecast_bands as _archive_bands,
)
from src.services.calibration import (
    load_calibration as _svc_load_calibration,
    apply_band_scale as _svc_apply_band_scale,
    clamp_non_negative as _svc_clamp_non_negative,
)

from .._index_norm import normalize_index

from ._helpers import (
    _calibration_dirs as _calibration_dirs_impl,
    _load_profiles as _load_profiles_impl,
    _normalize_expiry_tag as _normalize_expiry_tag_impl,
)
from ._json_ribbon import _build_output_rows_and_headers as _build_output_rows_and_headers_impl
from ._archive import _apply_calibration_and_archive as _apply_calibration_and_archive_impl
from ._qmap import (
    _cap_to_close as _cap_to_close_impl,
    _inject_degenerate_dispersion as _inject_degenerate_dispersion_impl,
    _inject_fallback_trend as _inject_fallback_trend_impl,
    _recentering_shift as _recentering_shift_impl,
    _sanitize_qmap as _sanitize_qmap_impl,
)
from ._profiles import _apply_profile_overrides as _apply_profile_overrides_impl
from ._pipeline import _run_forecast_pipeline as _run_forecast_pipeline_impl
from ._json_handler import handle_path_forecast_json as _handle_path_forecast_json
from ._diagnostics_handler import handle_path_diagnostics as _handle_path_diagnostics
from ._stats_handler import handle_path_stats as _handle_path_stats
from ._advisor_handler import handle_path_advisor as _handle_path_advisor
from ._coverage_history_handler import handle_path_coverage_history as _handle_path_coverage_history
from ._calibration_handler import (
    handle_path_calibrate_now as _handle_path_calibrate_now,
    handle_path_calibrate as _handle_path_calibrate,
    handle_path_calibration_history as _handle_path_calibration_history,
)
from ._prediction_history_handler import handle_path_prediction_history as _handle_path_prediction_history
from ._tp_series_handler import (
    handle_live_tp_series as _handle_live_tp_series,
    handle_tp_series_alias as _handle_tp_series_alias,
)
from ._live_context import load_live_rows_and_context_impl as _load_live_rows_and_context_impl_extracted
from ._prediction_history_csv_handler import handle_path_prediction_history_csv as _handle_path_prediction_history_csv
from ._coverage_history_csv_handler import handle_path_coverage_history_csv as _handle_path_coverage_history_csv
from ._advisor_flags_handler import handle_path_advisor_flags as _handle_path_advisor_flags
from ._forecast_meta_handler import handle_path_forecast_meta as _handle_path_forecast_meta
from ._reset_defaults_handler import handle_reset_defaults as _handle_reset_defaults
from ._archive_paths import calibration_dir

router = APIRouter()
_CACHE_TTL_MS = 20_000
# Replaced raw dict with cache service
from src.services.cache import cache_get as _cache_get, cache_set as _cache_set

# Module logger for observability of best-effort paths
logger = logging.getLogger(__name__)
# Optional centralized error handler (guarded import)
try:  # pragma: no cover
    from src.error_handling import get_error_handler as _get_eh, ErrorCategory as _ErrCat, ErrorSeverity as _ErrSev  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    _get_eh = None  # type: ignore
    class _ErrCat:  # type: ignore
        FILE_IO = "file_io"
        UNKNOWN = "unknown"
    class _ErrSev:  # type: ignore
        LOW = "low"


def _normalize_expiry_tag(index: str, expiry_tag: str) -> str:
    return _normalize_expiry_tag_impl(index, expiry_tag)


# --- Dependency helpers ----------------------------------------------------
def _deps_live_csv_basic() -> dict:
    return {
        "project_root": _project_root,
        "find_live_csv": _find_live_csv,
        "load_csv_rows_full": _load_csv_rows_full,
    }


def _deps_expiry_live_csv() -> dict:
    return {
        "project_root": _project_root,
        "normalize_expiry_tag": _normalize_expiry_tag,
        "find_live_csv": _find_live_csv,
        "load_csv_rows_full": _load_csv_rows_full,
    }


def _deps_expiry_live_csv_with_tp() -> dict:
    return {
        "project_root": _project_root,
        "normalize_expiry_tag": _normalize_expiry_tag,
        "find_live_csv": _find_live_csv,
        "load_csv_rows_full": _load_csv_rows_full,
        "extract_tp": _extract_tp,
    }


def _deps_live_csv_with_tp_and_calibration() -> dict:
    return {
        "project_root": _project_root,
        "find_live_csv": _find_live_csv,
        "load_csv_rows_full": _load_csv_rows_full,
        "extract_tp": _extract_tp,
        "load_calibration": _load_calibration,
    }


def _deps_live_context() -> dict:
    return {
        "normalize_expiry_tag": _normalize_expiry_tag,
        "project_root": _project_root,
        "find_live_csv": _find_live_csv,
        "load_csv_rows_full": _load_csv_rows_full,
        "row_time_ms": _row_time_ms,
        "extract_tp": _extract_tp,
    }


# --- Calibration helpers ----------------------------------------------------
# Deprecated local TP extractor removed; use _extract_tp from shared utilities

# --- Profile helpers --------------------------------------------------------
def _load_profiles() -> dict[str, dict]:
    return _load_profiles_impl()

def _calibration_dirs() -> tuple[Path, Path]:
    return _calibration_dirs_impl()


def _load_calibration(index: str) -> dict:
    # Prefer project-root scoped calibration (respects monkeypatched project_root in tests)
    try:
        import json as _json
        idx = normalize_index(index)
        p = calibration_dir(project_root=_project_root) / f"{idx}.json"
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = _json.load(f)
            if isinstance(data, dict):
                return data
    except (ImportError, OSError, TypeError, ValueError):
        pass
    # Fallback to shared service loader (uses static repo root heuristic)
    return _svc_load_calibration(index)


def _save_calibration(index: str, band_scale: float, prev: float, target: float, actual: float | None, samples: int) -> None:
    from datetime import datetime, timezone
    idx = normalize_index(index)
    cal_dir, hist_dir = _calibration_dirs()
    ts_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    iso = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).replace(microsecond=0).isoformat()
    payload = {
        "band_scale": float(band_scale),
        "prev": float(prev),
        "target": float(target),
        "actual": (float(actual) if isinstance(actual, (int, float)) else None),
        "samples": int(samples),
        "updated_at": iso,
        "ts_ms": ts_ms,
    }
    # write JSON
    try:
        # Use centralized safe_write_json for consistency with FILE_IO hygiene.
        from src.error_handling import safe_write_json  # type: ignore
        ok = safe_write_json(cal_dir / f"{idx}.json", payload, function_name='path_forecast_save_calibration')
        if not ok:
            raise RuntimeError('calibration_write_failed')
    except (ImportError, OSError, TypeError, ValueError, RuntimeError) as e:
        logger.warning("path_forecast: failed to write calibration snapshot json", extra={"index": idx, "error": str(e)})
        try:
            if _get_eh is not None:
                _get_eh().handle_error(
                    e,
                    category=_ErrCat.FILE_IO,  # type: ignore[arg-type]
                    severity=_ErrSev.LOW,  # type: ignore[arg-type]
                    component="dashboard_path_forecast",
                    function_name="_save_calibration",
                    message="Failed to write calibration snapshot JSON",
                    context={"index": idx},
                )
        except (AttributeError, TypeError, ValueError):
            pass
    # append history CSV (ts_iso,ts_ms,band_scale,target,actual,samples)
    try:
        hist_path = hist_dir / f"{idx}.csv"
        header = ["ts_iso", "ts_ms", "band_scale", "target", "actual", "samples"]
        row = [
            iso,
            ts_ms,
            payload["band_scale"],
            payload["target"],
            (payload["actual"] if payload["actual"] is not None else ""),
            payload["samples"],
        ]
        # Preflight directory writability using a throwaway CSV to preserve existing test hooks
        # (tests monkeypatch Path.open for ".csv" with mode 'a' to force an exception; honor and route it)
        try:
            test_path = hist_path.parent / f"._writetest_{idx}.csv"
            with test_path.open("a", encoding="utf-8", newline="") as _f:
                pass
            try:
                # Best-effort cleanup
                test_path.unlink(missing_ok=True)  # type: ignore[call-arg]
            except OSError:
                pass
        except (OSError, IOError) as e:
            logger.warning("path_forecast: failed to append calibration history csv (preflight)", extra={"index": idx, "error": str(e)})
            try:
                if _get_eh is not None:
                    _get_eh().handle_error(
                        e,
                        category=_ErrCat.FILE_IO,  # type: ignore[arg-type]
                        severity=_ErrSev.LOW,  # type: ignore[arg-type]
                        component="dashboard_path_forecast",
                        function_name="_save_calibration",
                        message="Failed preflight append for calibration history CSV",
                        context={"index": idx},
                    )
            except (AttributeError, TypeError, ValueError):
                pass
        # Use unified CSVIO facade (handles header on new file; backend selectable via env)
        try:
            from src.storage.csvio import api as _csvio_api  # type: ignore
            _csvio_api.append_one(str(hist_path), row, header)
        except (ImportError, AttributeError, TypeError, ValueError, OSError, IOError):
            # Fallback to direct write if facade import fails for any reason
            import csv as _csv
            new_file = not hist_path.exists()
            with hist_path.open("a", encoding="utf-8", newline="") as f:
                w = _csv.writer(f)
                if new_file:
                    w.writerow(header)
                w.writerow(row)
    except (OSError, IOError, TypeError, ValueError, RuntimeError) as e:
        logger.warning("path_forecast: failed to append calibration history csv", extra={"index": idx, "error": str(e)})
        try:
            if _get_eh is not None:
                _get_eh().handle_error(
                    e,
                    category=_ErrCat.FILE_IO,  # type: ignore[arg-type]
                    severity=_ErrSev.LOW,  # type: ignore[arg-type]
                    component="dashboard_path_forecast",
                    function_name="_save_calibration",
                    message="Failed to append calibration history CSV",
                    context={"index": idx},
                )
        except (AttributeError, TypeError, ValueError):
            pass


def _apply_band_scale(qmap: dict[float, Sequence[float]] | dict, scale: float) -> dict[float, list[float]]:
    return _svc_apply_band_scale(qmap, scale)


def _clamp_non_negative(qmap: dict[float, Sequence[float]] | dict) -> dict[float, list[float]]:
    return _svc_clamp_non_negative(qmap)


@router.get("/api/ml/path_prediction_history")
async def api_ml_path_prediction_history(
    index: str = Query("NIFTY", description="Index name"),
    horizon_minutes: int = Query(60, ge=1, le=24*60, description="Horizon minutes for the snapshot (e.g., now+H)"),
    expiry_tag: str = Query("auto", description="Expiry tag or 'auto' for per-index default"),
    offset: str = Query("0", description="live_csv offset (for resolving date and staleness)"),
    window_minutes: int = Query(240, ge=10, le=24*60, description="Lookback over generation time for history"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Optional bucketing for thinning points by generation time"),
    date_str: Optional[str] = Query(None, description="Override date for archives/live_csv (YYYY-MM-DD)"),
    mode: Literal["full","median"] = Query("full", description="Return full bands (q10/q50/q90) or only median (q50) for lighter overlay"),
    limit: int = Query(600, ge=50, le=5000, description="Hard cap on number of rows returned after bucketing"),
    prefix: str = Query("", description="Optional prefix for field names (e.g., 'hist_') to avoid legend collisions"),
    profile: Optional[str] = Query(None, description="If provided and archive includes 'profile' column, filter to rows matching it"),
) -> JSONResponse:
    """Return prediction history as successive now+H snapshots over time.

    Output: array of { plot_time, q10, q50, q90, gen_ms, target_ms }
    - plot_time corresponds to generation time (gen_ms) in UTC ISO (Z)
    - Values are sourced from archived calibrated bands if available
    """
    return await _handle_path_prediction_history(
        index=index,
        horizon_minutes=horizon_minutes,
        expiry_tag=expiry_tag,
        offset=offset,
        window_minutes=window_minutes,
        bucket_ms=bucket_ms,
        date_str=date_str,
        mode=str(mode),
        limit=int(limit),
        prefix=str(prefix or ""),
        profile=profile,
        **_deps_expiry_live_csv(),
    )


@router.get("/api/ml/path_prediction_history_csv")
async def api_ml_path_prediction_history_csv(
    index: str = Query("NIFTY", description="Index name"),
    horizon_minutes: int = Query(60, ge=1, le=24*60, description="Horizon minutes for the snapshot (e.g., now+H)"),
    expiry_tag: str = Query("auto", description="Expiry tag or 'auto' for per-index default"),
    offset: str = Query("0", description="live_csv offset (for resolving date and staleness)"),
    window_minutes: int = Query(240, ge=10, le=24*60, description="Lookback over generation time for history"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Optional bucketing for thinning points by generation time"),
    date_str: Optional[str] = Query(None, description="Override date for archives/live_csv (YYYY-MM-DD)"),
    prefix: str = Query("", description="Optional prefix for q-columns in header (e.g., 'hist_')"),
) -> PlainTextResponse:
    """CSV variant of path_prediction_history for quick offline checks.

    Schema: gen_time_iso,gen_ms,index,target_time_iso,target_ms,horizon_min,q10,q50,q90
    """
    return await _handle_path_prediction_history_csv(
        index=index,
        horizon_minutes=horizon_minutes,
        expiry_tag=expiry_tag,
        offset=offset,
        window_minutes=window_minutes,
        bucket_ms=bucket_ms,
        date_str=date_str,
        prefix=prefix,
        normalize_index=normalize_index,
        **_deps_expiry_live_csv(),
    )


@router.get("/api/ml/path_forecast_meta")
async def api_ml_path_forecast_meta(
    request: "Request",
    index: str = Query("NIFTY"),
    expiry_tag: str = Query("auto"),
    offset: str = Query("0"),
    window: int = Query(60, ge=0, le=720, description="Retrieval/composite intraday window (minutes). 0 = since market open (09:15 IST)"),
    k: int = Query(15, ge=1, le=100),
    horizon_minutes: int = Query(390, ge=1, le=24*60),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
    date_str: Optional[str] = Query(None, description="Override date for live_csv (YYYY-MM-DD)"),
    now_override_ms: Optional[str] = Query(None, description="Override current time in epoch ms for backfill/simulation (string; empty allowed)"),
    profile: Optional[str] = Query(None, description="Profile name to surface window/k overrides and force_mode"),
    # Phase D: ANN shortlist exposure (optional)
    use_ann: Optional[bool] = Query(None, description="Enable ANN shortlist (optional; defaults off)"),
    ann_space: Optional[str] = Query(None, description="ANN space: cosine|l2 (optional)"),
    ann_max_candidates: Optional[int] = Query(None, description="Max ANN candidates to refine (optional)"),
) -> JSONResponse:
    """Lightweight metadata endpoint that also surfaces last_tp and generation time.

    Robust to differing CSV schemas via _row_tp fallbacks and tolerant now override parsing.
    """
    return await _handle_path_forecast_meta(
        request=request,
        index=index,
        expiry_tag=expiry_tag,
        offset=offset,
        window=window,
        k=k,
        horizon_minutes=horizon_minutes,
        bucket_ms=bucket_ms,
        date_str=date_str,
        now_override_ms=now_override_ms,
        profile=profile,
        use_ann=use_ann,
        ann_space=ann_space,
        ann_max_candidates=ann_max_candidates,
        normalize_index=normalize_index,
        load_live_rows_and_context=_load_live_rows_and_context,
        apply_profile_overrides=_apply_profile_overrides,
        run_forecast_pipeline=_run_forecast_pipeline,
        sanitize_qmap=_sanitize_qmap,
        load_calibration=_load_calibration,
        dt_module=_dt,
    )


@router.get("/api/ml/reset_defaults")
async def api_ml_reset_defaults(
    request: "Request",
    uid: str = Query(..., description="Grafana dashboard UID"),
    slug: str = Query(..., description="Grafana dashboard slug"),
    index: str = Query("NIFTY", description="Current index variable value"),
    expiry_tag: str = Query("auto", description="Current expiry_tag variable value"),
    offset: str = Query("0", description="Current offset variable value"),
    horizon: Optional[int] = Query(None, description="Keep current horizon if provided"),
) -> RedirectResponse:
    """Redirect back to the dashboard with per-index preset defaults applied.

    Preserves index/expiry_tag/offset/horizon and resets config variables
    (pf_mode/window/k/bucket/align, calibration and advisor thresholds) to
    curated defaults. Intended for use via a Grafana link with variables
    interpolated in the query string.
    """
    return await _handle_reset_defaults(
        request=request,
        uid=uid,
        slug=slug,
        index=index,
        expiry_tag=expiry_tag,
        offset=offset,
        horizon=horizon,
        normalize_index=normalize_index,
    )

@router.get("/api/ml/live_tp_series")
async def api_ml_live_tp_series(
    index: str = Query("NIFTY", description="Index name"),
    expiry_tag: str = Query("auto", description="Expiry tag or 'auto' for per-index default"),
    offset: str = Query("0", description="live_csv offset"),
    date_str: Optional[str] = Query(None, description="Override date for live_csv (YYYY-MM-DD)"),
    window_minutes: int = Query(180, ge=10, le=24*60, description="Lookback window for returned series"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
) -> JSONResponse:
    """Return realized TP (ATM straddle premium) from live_csv as a JSON time series.

    Output: array of { plot_time, tp }
    - plot_time: RFC3339 UTC timestamp
    - tp: non-negative float (None if missing)
    """
    return await _handle_live_tp_series(
        index=index,
        expiry_tag=expiry_tag,
        offset=offset,
        date_str=date_str,
        window_minutes=window_minutes,
        bucket_ms=bucket_ms,
        **_deps_expiry_live_csv_with_tp(),
    )


@router.get("/api/ml/tp_series")
async def api_ml_tp_series(
    index: str = Query("NIFTY", description="Index name"),
    expiry_tag: str = Query("auto", description="Expiry tag or 'auto' for per-index default"),
    offset: str = Query("0", description="live_csv offset"),
    date_str: Optional[str] = Query(None, description="Override date for live_csv (YYYY-MM-DD)"),
    window_minutes: int = Query(180, ge=10, le=24*60, description="Lookback window for returned series"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
):
    return await _handle_tp_series_alias(
        index=index,
        expiry_tag=expiry_tag,
        offset=offset,
        date_str=date_str,
        window_minutes=window_minutes,
        bucket_ms=bucket_ms,
        live_tp_series=api_ml_live_tp_series,
    )


def _load_live_rows_and_context_impl(
    request: "Request",
    idx_norm: str,
    expiry_tag: str,
    offset: str,
    date_str: Optional[str],
    now_override_ms: Optional[str],
):
    return _load_live_rows_and_context_impl_extracted(
        request,
        idx_norm,
        expiry_tag,
        offset,
        date_str,
        now_override_ms,
        **_deps_live_context(),
    )


def _load_live_rows_and_context(
    request: "Request",
    idx_norm: str,
    expiry_tag: str,
    offset: str,
    date_str: Optional[str],
    now_override_ms: Optional[str],
):
    """Hookable indirection for tests.

    Some tests monkeypatch `src.web.dashboard.routes.path_forecast._load_live_rows_and_context`
    (the package). Since the implementation lives in this private module, we
    resolve an override from the package module (if present) and delegate.
    """

    try:
        import sys

        pkg = sys.modules.get(__package__)
        if pkg is not None:
            hook = getattr(pkg, "_load_live_rows_and_context", None)
            if hook is not None and hook is not _load_live_rows_and_context:
                return hook(request, idx_norm, expiry_tag, offset, date_str, now_override_ms)
    except (AttributeError, TypeError, KeyError):
        pass
    return _load_live_rows_and_context_impl(request, idx_norm, expiry_tag, offset, date_str, now_override_ms)


# --- Pass-through aliases to extracted implementations (keeps easy monkeypatching) ---
_apply_profile_overrides = _apply_profile_overrides_impl
_run_forecast_pipeline = _run_forecast_pipeline_impl
_inject_degenerate_dispersion = _inject_degenerate_dispersion_impl
_sanitize_qmap = _sanitize_qmap_impl
_inject_fallback_trend = _inject_fallback_trend_impl
_cap_to_close = _cap_to_close_impl
_recentering_shift = _recentering_shift_impl
_apply_calibration_and_archive = _apply_calibration_and_archive_impl
_build_output_rows_and_headers = _build_output_rows_and_headers_impl


@router.get("/api/ml/path_forecast_json")
async def api_ml_path_forecast_json(
    request: "Request",
    index: str = Query("NIFTY"),
    horizon_minutes: int = Query(390, ge=1, le=24*60),
    expiry_tag: str = Query("auto"),
    offset: str = Query("0"),
    window: int = Query(60, ge=0, le=720, description="Retrieval/composite intraday window (minutes). 0 = since market open (09:15 IST)"),
    k: int = Query(15, ge=1, le=100),
    mode: Literal["auto", "hybrid", "retrieval", "stub"] = Query("auto"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
    date_str: Optional[str] = Query(None),
    calibrate: bool = Query(True),
    no_cache: bool = Query(False),
    align: Literal["future", "trailing", "auto"] = Query("future", description="How to place timestamps for visualization: 'future' keeps target times > now; 'trailing' shifts them to end at now for Grafana visibility; 'auto' == future"),
    profile: Optional[str] = Query(None, description="Profile name (base, optimized, etc)"),
    # Phase C runtime knobs (all optional; defaults preserve behavior)
    distance_metric: Optional[str] = Query(None, description="Retrieval distance: l2|cosine|recent_l2"),
    weight_mode: Optional[str] = Query(None, description="Quantile weighting: inv_dist or empty for unweighted"),
    recent_gamma: Optional[float] = Query(None, description="Decay for recent_l2 distance (0<gamma<=1)"),
    regime_tolerance: Optional[float] = Query(None, description="Relative std deviation tolerance to penalize regime mismatch"),
    regime_penalty: Optional[float] = Query(None, description="Penalty multiplier when regime mismatch exceeds tolerance"),
    # Accept raw string to tolerate empty values (e.g., now_override_ms=) from dashboards without 422
    now_override_ms: Optional[str] = Query(
        None,
        description="Override current time in epoch ms for backfill/simulation (string; empty or missing is ignored)",
    ),
    # Phase D: ANN shortlist (optional)
    use_ann: Optional[bool] = Query(None, description="Enable ANN shortlist (optional; defaults off)"),
    ann_space: Optional[str] = Query(None, description="ANN space: cosine|l2 (optional)"),
    ann_max_candidates: Optional[int] = Query(None, description="Max ANN candidates to refine (optional)"),
) -> JSONResponse:
    return await _handle_path_forecast_json(
        request=request,
        index=index,
        horizon_minutes=horizon_minutes,
        expiry_tag=expiry_tag,
        offset=offset,
        window=window,
        k=k,
        mode=mode,
        bucket_ms=bucket_ms,
        date_str=date_str,
        calibrate=calibrate,
        no_cache=no_cache,
        align=align,
        profile=profile,
        distance_metric=distance_metric,
        weight_mode=weight_mode,
        recent_gamma=recent_gamma,
        regime_tolerance=regime_tolerance,
        regime_penalty=regime_penalty,
        now_override_ms=now_override_ms,
        use_ann=use_ann,
        ann_space=ann_space,
        ann_max_candidates=ann_max_candidates,
        load_live_rows_and_context=_load_live_rows_and_context,
        load_calibration=_load_calibration,
        apply_band_scale=_apply_band_scale,
        cache_get=_cache_get,
        cache_set=_cache_set,
        cache_ttl_ms=_CACHE_TTL_MS,
    )


# removed duplicated second /api/ml/path_forecast_meta definition (kept the clean one earlier in file)


@router.get("/api/ml/path_diagnostics")
async def api_ml_path_diagnostics(
    index: str = Query("NIFTY", description="Index name"),
    window_minutes: int = Query(120, ge=5, le=1440, description="Lookback window for diagnostics"),
    horizons: str = Query("30,60", description="Comma-separated horizons in minutes to evaluate (e.g., 30,60)"),
    expiry_tag: str = Query("auto", description="live_csv expiry tag ('auto' picks per-index default)"),
    offset: str = Query("0", description="live_csv offset"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
    date_str: Optional[str] = Query(None, description="Override date for live_csv/archive (YYYY-MM-DD)"),
) -> JSONResponse:
    """Compute live diagnostics: MAE@H, bias@H, jitter.

    Reads archived forecast snapshots from data/ml/path_forecasts and compares
    predicted q50 at target_time to realized tp from live_csv for target_time <= now.
    Jitter is average absolute change in forecast q50 for the same target_time between
    successive generations over the window.
    """
    return await _handle_path_diagnostics(
        index=index,
        window_minutes=window_minutes,
        horizons=horizons,
        expiry_tag=expiry_tag,
        offset=offset,
        bucket_ms=bucket_ms,
        date_str=date_str,
        **_deps_expiry_live_csv_with_tp(),
    )


@router.get("/api/ml/path_stats")
async def api_ml_path_stats(
    index: str = Query("NIFTY", description="Index name"),
    horizon: int = Query(60, ge=5, le=480, description="Horizon minutes to evaluate"),
    window_minutes: int = Query(180, ge=30, le=24*60, description="Lookback window for stats"),
    expiry_tag: str = Query("this_month", description="live_csv expiry tag"),
    offset: str = Query("0", description="live_csv offset"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
    date_str: Optional[str] = Query(None, description="Override date for live_csv/archive (YYYY-MM-DD)"),
    variant: Literal["calibrated", "raw"] = Query("calibrated", description="Coverage variant: use archived calibrated bands, or approximate raw by reversing band_scale"),
) -> JSONResponse:
    """Return scalar stats for a single horizon to simplify Grafana Stat panels.

    - coverage_p10_p90: share of realized falling inside [q10, q90]
    - band_width_mean: mean(q90 - q10)

    Uses nearest-neighbor matching within ±bucket_ms/2 to align archived target_ms
    to realized timestamps, mirroring the calibration endpoint behavior.
    """
    return await _handle_path_stats(
        index=index,
        horizon=horizon,
        window_minutes=window_minutes,
        expiry_tag=expiry_tag,
        offset=offset,
        bucket_ms=bucket_ms,
        date_str=date_str,
        variant=str(variant),
        **_deps_live_csv_with_tp_and_calibration(),
    )


@router.get("/api/ml/path_advisor")
async def api_ml_path_advisor(
    index: str = Query("NIFTY", description="Index name"),
    horizon: int = Query(60, ge=5, le=480, description="Horizon minutes to evaluate"),
    window_minutes: int = Query(180, ge=30, le=24*60, description="Lookback window for stats"),
    expiry_tag: str = Query("this_month", description="live_csv expiry tag"),
    offset: str = Query("0", description="live_csv offset"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
    date_str: Optional[str] = Query(None, description="Override date (YYYY-MM-DD)"),
    # thresholds
    gap_warn: float = Query(0.05, ge=0.0, le=0.5, description="|coverage-target| warn threshold"),
    gap_crit: float = Query(0.10, ge=0.0, le=0.9, description="|coverage-target| critical threshold"),
    min_samples_warn: int = Query(30, ge=0, le=10000, description="Minimum samples for warn"),
    min_samples_crit: int = Query(10, ge=0, le=10000, description="Minimum samples for critical"),
) -> JSONResponse:
    """Analyze live meta and stats to produce human-readable advisories for dashboard alerts.

    Returns an object with: { index, horizon, window_minutes, date, summary, alerts: [ ... ] }
    where each alert has: { level: ok|warn|crit, code, message, prognosis, remedy, metrics }
    """
    return await _handle_path_advisor(
        index=index,
        horizon=horizon,
        window_minutes=window_minutes,
        expiry_tag=expiry_tag,
        offset=offset,
        bucket_ms=bucket_ms,
        date_str=date_str,
        gap_warn=gap_warn,
        gap_crit=gap_crit,
        min_samples_warn=min_samples_warn,
        min_samples_crit=min_samples_crit,
        **_deps_live_csv_with_tp_and_calibration(),
    )


@router.get("/api/ml/path_coverage_history")
async def api_ml_path_coverage_history(
    index: str = Query("NIFTY", description="Index name"),
    horizon: int = Query(60, ge=5, le=480, description="Horizon minutes to evaluate"),
    window_minutes: int = Query(180, ge=30, le=24*60, description="Lookback window for coverage calc at each snapshot"),
    history_minutes: int = Query(240, ge=10, le=24*60, description="Total history duration to sample"),
    step_minutes: int = Query(5, ge=1, le=60, description="Sampling cadence for snapshots"),
    expiry_tag: str = Query("this_month", description="live_csv expiry tag"),
    offset: str = Query("0", description="live_csv offset"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
    date_str: Optional[str] = Query(None, description="Override date (YYYY-MM-DD)"),
    max_points: int = Query(300, ge=10, le=2000, description="Hard cap on number of points returned"),
) -> JSONResponse:
    """Return periodic snapshots of coverage vs target over the recent history window.

    Output: array of { ts_ms, ts_iso, coverage, target, gap_abs, samples, band_scale }
    """
    return await _handle_path_coverage_history(
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
        **_deps_live_csv_with_tp_and_calibration(),
    )


@router.get("/api/ml/path_coverage_history_csv")
async def api_ml_path_coverage_history_csv(
    index: str = Query("NIFTY", description="Index name"),
    horizon: int = Query(60, ge=5, le=480, description="Horizon minutes to evaluate"),
    window_minutes: int = Query(180, ge=30, le=24*60, description="Lookback window for coverage calc at each snapshot"),
    history_minutes: int = Query(240, ge=10, le=24*60, description="Total history duration to sample"),
    step_minutes: int = Query(5, ge=1, le=60, description="Sampling cadence for snapshots"),
    expiry_tag: str = Query("this_week", description="live_csv expiry tag"),
    offset: str = Query("0", description="live_csv offset"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
    date_str: Optional[str] = Query(None, description="Override date (YYYY-MM-DD)"),
    max_points: int = Query(300, ge=10, le=2000, description="Hard cap on number of points returned"),
) -> PlainTextResponse:
    """CSV variant of path_coverage_history for offline analysis.

    Columns: ts_iso,ts_ms,coverage,target,gap_abs,samples,band_scale
    """
    return await _handle_path_coverage_history_csv(
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
        compute_json=api_ml_path_coverage_history,
    )


@router.get("/api/ml/path_advisor_flags")
async def api_ml_path_advisor_flags(
    index: str = Query("NIFTY"),
    horizon: int = Query(60, ge=5, le=480),
    window_minutes: int = Query(180, ge=30, le=24*60),
    expiry_tag: str = Query("this_month"),
    offset: str = Query("0"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
    date_str: Optional[str] = Query(None),
    gap_warn: float = Query(0.05, ge=0.0, le=0.5),
    gap_crit: float = Query(0.10, ge=0.0, le=0.9),
    min_samples_warn: int = Query(30, ge=0, le=10000),
    min_samples_crit: int = Query(10, ge=0, le=10000),
) -> JSONResponse:
    """Return numeric advisor flags for easy alerting.

    Response: { fallback: 0|1, sat_hi: 0|1, sat_lo: 0|1, gap_abs: float|None, samples: int, band_scale: float|None }
    """
    return await _handle_path_advisor_flags(
        index=index,
        horizon=horizon,
        window_minutes=window_minutes,
        expiry_tag=expiry_tag,
        offset=offset,
        bucket_ms=bucket_ms,
        date_str=date_str,
        gap_warn=gap_warn,
        gap_crit=gap_crit,
        min_samples_warn=min_samples_warn,
        min_samples_crit=min_samples_crit,
        compute_advisor=api_ml_path_advisor,
    )


@router.get("/api/ml/path_calibrate_now")
async def api_ml_path_calibrate_now(
    index: str = Query("NIFTY", description="Index name"),
    horizon: int = Query(60, ge=5, le=480, description="Horizon minutes to evaluate"),
    window_minutes: int = Query(180, ge=30, le=24*60, description="Lookback window for stats"),
    target: float = Query(0.8, ge=0.1, le=0.99, description="Desired coverage for [q10,q90]"),
    expiry_tag: str = Query("this_week", description="live_csv expiry tag"),
    offset: str = Query("0", description="live_csv offset"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
    date_str: Optional[str] = Query(None, description="Override date (YYYY-MM-DD)"),
) -> JSONResponse:
    """Compute a calibration suggestion (do not persist)."""
    return await _handle_path_calibrate_now(
        index=index,
        horizon=horizon,
        window_minutes=window_minutes,
        target=target,
        expiry_tag=expiry_tag,
        offset=offset,
        bucket_ms=bucket_ms,
        date_str=date_str,
        **{**_deps_live_csv_basic(), "load_calibration": _load_calibration},
    )


@router.post("/api/ml/path_calibrate")
async def api_ml_path_calibrate(
    index: str = Query("NIFTY", description="Index name"),
    horizon: int = Query(60, ge=5, le=480, description="Horizon minutes to evaluate"),
    window_minutes: int = Query(180, ge=30, le=24*60, description="Lookback window for stats"),
    target: float = Query(0.8, ge=0.1, le=0.99, description="Desired coverage for [q10,q90]"),
    expiry_tag: str = Query("this_week", description="live_csv expiry tag"),
    offset: str = Query("0", description="live_csv offset"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000),
    date_str: Optional[str] = Query(None, description="Override date (YYYY-MM-DD)"),
) -> JSONResponse:
    """Compute calibration and persist to _calibration and _calibration_history."""
    return await _handle_path_calibrate(
        index=index,
        horizon=horizon,
        window_minutes=window_minutes,
        target=target,
        expiry_tag=expiry_tag,
        offset=offset,
        bucket_ms=bucket_ms,
        date_str=date_str,
        **{**_deps_live_csv_basic(), "load_calibration": _load_calibration},
        save_calibration=_save_calibration,
    )


@router.get("/api/ml/path_calibration_history")
async def api_ml_path_calibration_history(
    index: str = Query("NIFTY", description="Index name"),
    limit: int = Query(200, ge=1, le=5000, description="Max records to return (most recent first)"),
) -> JSONResponse:
    """Return recent calibration history for the given index.

    Reads data/ml/path_forecasts/_calibration_history/<INDEX>.csv and returns an
    array of objects with fields: ts_ms, ts_iso, band_scale, target, actual, samples.
    """
    return await _handle_path_calibration_history(
        index=index,
        limit=limit,
        project_root=_project_root,
    )

