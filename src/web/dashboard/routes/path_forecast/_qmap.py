from __future__ import annotations

import logging
from collections.abc import Sequence

from src.path_forecast.common import extract_tp as _extract_tp, row_time_ms as _row_time_ms
from src.services.calibration import clamp_non_negative as _clamp_non_negative

logger = logging.getLogger(__name__)


def _inject_degenerate_dispersion(
    idx: str,
    horizon_minutes: int,
    times: list[int],
    qmap: dict[float, list[float]],
    diag: dict[str, object],
) -> None:
    """Detect completely flat ribbon (q10==q50==q90 for >80% points) and inject synthetic dispersion.

    This prevents the Grafana ribbon from appearing frozen when upstream retrieval collapses variance.
    Strategy: compute a tiny band around q50 using either recent TP stdev or a fixed pct (fallback 1%).
    We mark diagnostics so downstream meta table can surface the adjustment: keys:
        ribbon_degenerate_detected=1, ribbon_dispersion_pct=<pct>, ribbon_injected_points=<n>
    Safe no-op if data already has dispersion or arrays missing.
    """

    try:
        q10 = list(qmap.get(0.1) or qmap.get("0.1") or [])
        q50 = list(qmap.get(0.5) or qmap.get("0.5") or [])
        q90 = list(qmap.get(0.9) or qmap.get("0.9") or [])
        if not q50 or not q10 or not q90:
            return
        flat_cnt = 0
        for i in range(min(len(q10), len(q50), len(q90))):
            v10 = q10[i]
            v50 = q50[i]
            v90 = q90[i]
            if all(isinstance(v, (int, float)) for v in (v10, v50, v90)) and v10 == v50 == v90:
                flat_cnt += 1
        total = min(len(q10), len(q50), len(q90))
        if total == 0:
            return
        flat_share = flat_cnt / float(total)
        # Require majority flat and at least 10 points to avoid early-session micro adjustments
        if flat_share < 0.8 or total < 10:
            return
        # Estimate dispersion from q50 intrinsic variance when available
        import statistics

        try:
            q50_vals = [float(v) for v in q50 if isinstance(v, (int, float))]
        except (TypeError, ValueError):
            q50_vals = []
        try:
            stdev_q50 = statistics.pstdev(q50_vals) if len(q50_vals) >= 2 else 0.0
        except (statistics.StatisticsError, TypeError, ValueError):
            stdev_q50 = 0.0
        base_pct = 0.01  # 1% default band
        if q50_vals:
            mean_q50 = sum(q50_vals) / len(q50_vals)
            try:
                ratio = (stdev_q50 / mean_q50) if mean_q50 > 0 else 0.0
            except (TypeError, ValueError, ZeroDivisionError):
                ratio = 0.0
            if ratio > 0.0005:
                base_pct = min(0.02, max(base_pct, 0.005 * ratio))
        injected = 0
        for i in range(total):
            v50 = q50[i]
            if not isinstance(v50, (int, float)):
                continue
            # Only adjust truly flat triplets
            if isinstance(q10[i], (int, float)) and isinstance(q90[i], (int, float)) and q10[i] == v50 == q90[i]:
                spread = max(0.0001, base_pct * float(v50))  # ensure non-zero
                q10[i] = max(0.0, float(v50) - spread)
                q90[i] = float(v50) + spread
                injected += 1
        # Replace arrays in qmap
        qmap[0.1] = q10
        qmap[0.5] = q50
        qmap[0.9] = q90
        diag["ribbon_degenerate_detected"] = 1
        diag["ribbon_dispersion_pct"] = base_pct
        diag["ribbon_injected_points"] = injected
        try:
            logger.info(
                "ribbon_degenerate_detected index=%s horizon=%s points=%d flat_share=%.2f pct=%.4f injected=%d",
                idx,
                str(horizon_minutes),
                total,
                flat_share,
                base_pct,
                injected,
            )
        except (TypeError, ValueError):
            pass
    except BaseException as e:
        import asyncio

        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        # Silent; do not disrupt main pipeline
        try:
            logger.debug("ribbon_degenerate_handler_failed index=%s", idx, exc_info=True)
        except (TypeError, ValueError):
            pass


def _sanitize_qmap(qmap: dict[float, list[float]] | dict) -> dict[float, list[float]]:
    """Replace any None/non-numeric entries in quantile arrays with 0.0.

    Defensive hardening for synthetic/edge test contexts where upstream pipeline
    may yield sparse arrays. Using 0.0 keeps subsequent float() casts and
    calibration math safe while preserving non-negativity guarantees. The
    fallback forecaster already generates non-negative values; retrieval/composite
    should not normally emit None, so this is effectively a no-op in production.
    """

    cleaned: dict[float, list[float]] = {}
    try:
        for q, arr in qmap.items():
            # Normalize key
            try:
                qf = float(q)
            except (TypeError, ValueError):
                continue
            seq: list[float] = []
            for v in (arr or []):  # type: ignore[union-attr]
                if isinstance(v, (int, float)):
                    seq.append(float(v))
                else:
                    # Substitute 0.0 for None/invalid entries
                    seq.append(0.0)
            cleaned[qf] = seq
    except (AttributeError, TypeError, ValueError):
        # On unexpected structure, fall back to original mapping casted to lists
        try:
            for k, v in qmap.items():
                cleaned[float(k)] = [float(x) if isinstance(x, (int, float)) else 0.0 for x in (v or [])]  # type: ignore[list-item]
        except (AttributeError, TypeError, ValueError):
            return {0.5: [0.0]}
    return cleaned


def _inject_fallback_trend(rows: list[dict], times: list[int], ref_now_ms: int, qmap: dict, diag: dict):
    try:
        tps: list[tuple[int, float]] = []
        for r in rows[-60:]:
            ems = _row_time_ms(r)
            if not isinstance(ems, int) or ems <= 0:
                continue
            tpv = _extract_tp(r)
            if isinstance(tpv, (int, float)):
                tps.append((ems, float(tpv)))
        if len(tps) >= 5 and times:
            tps_recent = tps[-15:]
            t0, v0 = tps_recent[0]
            t1, v1 = tps_recent[-1]
            dt_min = max(1.0, (t1 - t0) / 60000.0)
            slope = (v1 - v0) / dt_min
            for i, tgt_ms in enumerate(times):
                delta_min = (tgt_ms - ref_now_ms) / 60000.0 if ref_now_ms else 0.0
                for q in (0.5, 0.1, 0.9):
                    arr = qmap.get(q) or []
                    if i < len(arr) and isinstance(arr[i], (int, float)):
                        arr[i] = float(arr[i]) + slope * delta_min
            try:
                qmap = _clamp_non_negative(qmap)
            except (AttributeError, TypeError, ValueError):
                pass
            diag["fallback_trend_slope"] = slope
            diag["fallback_trend_points"] = len(tps_recent)
    except (AttributeError, KeyError, TypeError, ValueError):
        pass


def _cap_to_close(times: list[int], qmap: dict, ref_now_ms: int):
    try:
        from datetime import datetime, timezone, timedelta

        d = datetime.utcfromtimestamp(ref_now_ms / 1000).date()
        ist = timezone(timedelta(hours=5, minutes=30))
        close_dt = datetime(d.year, d.month, d.day, 15, 30, tzinfo=ist)
        close_ms = int(close_dt.timestamp() * 1000)
        if times:
            last_ok = -1
            for i, t in enumerate(times):
                try:
                    if int(t) <= close_ms:
                        last_ok = i
                    else:
                        break
                except (TypeError, ValueError, OverflowError):
                    break
            if last_ok >= 0 and last_ok < len(times) - 1:
                times[:] = list(times[: last_ok + 1])
                for q in (0.1, 0.5, 0.9):
                    seq = list(qmap.get(q) or [])
                    qmap[q] = seq[: last_ok + 1]
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass


def _recentering_shift(times: list[int], qmap: dict, last_tp: float, diag: dict):
    try:
        if times and isinstance(last_tp, (int, float)):
            q50_list_tmp = list(qmap.get(0.5) or [])
            first_idx = None
            for i, v in enumerate(q50_list_tmp):
                if isinstance(v, (int, float)):
                    first_idx = i
                    break
            if first_idx is not None:
                first_v = q50_list_tmp[first_idx]
                if not isinstance(first_v, (int, float)):
                    return
                first_q50 = float(first_v)
                shift = float(last_tp) - first_q50
                if shift != 0:
                    for q in (0.1, 0.5, 0.9):
                        seq = list(qmap.get(q) or [])
                        for j, vv in enumerate(seq):
                            if isinstance(vv, (int, float)):
                                seq[j] = float(vv) + shift
                        qmap[q] = seq
                    diag["post_shift"] = shift
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
