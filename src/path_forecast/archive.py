from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Sequence, Any


@dataclass
class ArchiveConfig:
    base_dir: Path  # typically project_root()/data/ml/path_forecasts


def _ensure_dir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def append_forecast_snapshot(
    cfg: ArchiveConfig,
    *,
    index: str,
    gen_ms: int,
    times: Sequence[int],
    qmap: Dict[float, Sequence[float]],
    meta: Dict[str, Any] | None = None,
) -> None:
    """Append a long-format snapshot of q50 forecasts for diagnostics.

    Primary archive (q50 only, stable schema):
      File: base_dir/<INDEX>/<YYYY-MM-DD>.csv
      Columns: gen_time_iso,gen_ms,index,mode,alpha,prior_days,k_used,window_used,target_time_iso,target_ms,horizon_min,q50

    Note: To keep backward compatibility for existing diagnostics, this file
    remains q50-only. See append_quantile_bands_snapshot for multi-quantile
    archival in a companion file.
    """
    try:
        idx = (index or "NIFTY").upper()
        gen_dt = _dt.datetime.fromtimestamp(gen_ms / 1000).replace(microsecond=0)
        day_str = gen_dt.strftime("%Y-%m-%d")
        out_dir = cfg.base_dir / idx
        _ensure_dir(out_dir)
        fpath = out_dir / f"{day_str}.csv"
        # Extract q50 path (tolerate mixed key types and ignore non-numeric keys)
        q50_key = None
        best_dist = None
        for k in (qmap or {}).keys():
            try:
                qf = float(k)
            except Exception:
                continue
            d = abs(qf - 0.5)
            if best_dist is None or d < best_dist:
                best_dist = d
                q50_key = k
        series = list(qmap.get(q50_key, ())) if q50_key is not None else []
        # Meta fields
        m = dict(meta or {})
        mode = str(m.get("mode") or m.get("mode_used") or "").lower()
        alpha = m.get("alpha", "")
        prior_days = m.get("prior_days", "")
        k_used = m.get("k_used", "")
        window_used = m.get("window_used", "")
        # Write header if new
        new_file = not fpath.exists()
        with fpath.open("a", encoding="utf-8", newline="") as f:
            if new_file:
                f.write(
                    "gen_time_iso,gen_ms,index,mode,alpha,prior_days,k_used,window_used,target_time_iso,target_ms,horizon_min,q50\n"
                )
            for i, tms in enumerate(times):
                try:
                    tgt_dt = _dt.datetime.fromtimestamp(tms / 1000).replace(microsecond=0)
                except Exception:
                    continue
                qv = series[i] if i < len(series) else ""
                horizon_min = max(0, int(round((tms - gen_ms) / 60000.0)))
                f.write(
                    f"{gen_dt.isoformat()},{gen_ms},{idx},{mode},{alpha},{prior_days},{k_used},{window_used},{tgt_dt.isoformat()},{tms},{horizon_min},{qv}\n"
                )
    except Exception:
        # Best-effort archival; never raise from API path
        return


def append_quantile_bands_snapshot(
    cfg: ArchiveConfig,
    *,
    index: str,
    gen_ms: int,
    times: Sequence[int],
    qmap: Dict[float, Sequence[float]],
    meta: Dict[str, Any] | None = None,
) -> None:
    """Append a companion multi-quantile snapshot for diagnostics and ribbons.

    File layout: base_dir/<INDEX>/<YYYY-MM-DD>_bands.csv
    Columns: gen_time_iso,gen_ms,index,target_time_iso,target_ms,horizon_min,profile,mode,<qXX columns>

    - The header is created on first write and then preserved. Subsequent writes
      project available quantiles onto the existing header; missing values are left blank.
    - This avoids changing the schema of the primary q50-only archive.
    """
    try:
        idx = (index or "NIFTY").upper()
        gen_dt = _dt.datetime.fromtimestamp(gen_ms / 1000).replace(microsecond=0)
        day_str = gen_dt.strftime("%Y-%m-%d")
        out_dir = cfg.base_dir / idx
        _ensure_dir(out_dir)
        fpath = out_dir / f"{day_str}_bands.csv"

        # Determine header quantile columns
        existing_cols: list[str] | None = None
        existing_all_cols: list[str] | None = None
        if fpath.exists():
            try:
                with fpath.open("r", encoding="utf-8") as rf:
                    first = rf.readline().strip()
                if first:
                    parts = [c.strip() for c in first.split(",")]
                    # Keep only q-prefixed columns to preserve order
                    existing_cols = [c for c in parts if c.lower().startswith("q")]
                    existing_all_cols = parts
            except Exception:
                existing_cols = None
                existing_all_cols = None

        def _numeric_qs() -> list[float]:
            out: list[float] = []
            for k in (qmap or {}).keys():
                try:
                    out.append(float(k))
                except Exception:
                    continue
            # sort/dedupe for stable header
            try:
                return sorted(set(out))
            except Exception:
                return out

        # If no existing header, use numeric quantiles from qmap sorted ascending
        if not existing_cols:
            qs_sorted = _numeric_qs() if qmap else [0.1, 0.5, 0.9]
            if not qs_sorted:
                qs_sorted = [0.1, 0.5, 0.9]
            qcols = [f"q{int(float(q)*100):02d}" for q in qs_sorted]
        else:
            qcols = existing_cols

        def _nearest_series(target_q: float) -> Sequence[float]:
            best_key = None
            best_d = None
            for k in (qmap or {}).keys():
                try:
                    qf = float(k)
                except Exception:
                    continue
                d = abs(qf - target_q)
                if best_d is None or d < best_d:
                    best_d = d
                    best_key = k
            if best_key is None:
                return []
            try:
                return qmap.get(best_key) or []
            except Exception:
                return []

        # Map from column name to series
        col_to_series: dict[str, Sequence[float]] = {}
        for qc in qcols:
            try:
                q = float(int(qc[1:]) / 100.0)
            except Exception:
                q = 0.5
            col_to_series[qc] = list(_nearest_series(q))

        new_file = not fpath.exists()
        with fpath.open("a", encoding="utf-8", newline="") as f:
            if new_file:
                header = [
                    "gen_time_iso","gen_ms","index","target_time_iso","target_ms","horizon_min",
                    "profile","mode",
                    *qcols,
                ]
                f.write(",".join(header) + "\n")
            for i, tms in enumerate(times):
                try:
                    tgt_dt = _dt.datetime.fromtimestamp(tms / 1000).replace(microsecond=0)
                except Exception:
                    continue
                horizon_min = max(0, int(round((tms - gen_ms) / 60000.0)))
                row = [
                    gen_dt.isoformat(), str(gen_ms), idx, tgt_dt.isoformat(), str(tms), str(horizon_min)
                ]
                # Include profile/mode if header includes them (new files will)
                if new_file or (isinstance(existing_all_cols, list) and "profile" in existing_all_cols):
                    prof = ""
                    try:
                        prof = str((meta or {}).get("profile") or (meta or {}).get("profile_name") or "")
                    except Exception:
                        prof = ""
                    row.append(prof)
                if new_file or (isinstance(existing_all_cols, list) and "mode" in existing_all_cols):
                    md = ""
                    try:
                        md = str((meta or {}).get("mode") or (meta or {}).get("mode_used") or "")
                    except Exception:
                        md = ""
                    row.append(md)
                for qc in qcols:
                    series = col_to_series.get(qc) or []
                    val = series[i] if i < len(series) else ""
                    row.append(str(val))
                f.write(",".join(row) + "\n")
    except Exception:
        # Best-effort; don't fail the caller
        return
