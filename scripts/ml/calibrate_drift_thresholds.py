#!/usr/bin/env python
"""Auto-calibrate static drift thresholds from rolling percentile baselines.

Logic:
- Reads in-memory rolling drift baselines via `rolling_mae.get_drift_baselines()`.
- For each (index,horizon) where counts >= --min-count, extracts percentiles:
  mae_ratio: p{warn_pctl*100}, p{crit_pctl*100}
  norm_ratio: p{warn_pctl*100}, p{crit_pctl*100}
  coverage_delta (lower tail): p{coverage_warn_low_pctl*100}, p{coverage_crit_low_pctl*100}
- Aggregates across horizons to produce recommended static global env overrides:
  * Use median of horizon-level warn candidates for WARN.
  * Use median of horizon-level crit candidates for CRIT.
  (Median is more robust than min/max against outliers.)
- Writes a JSON artifact summarizing per-horizon inputs + chosen recommendations.
- Prints ready-to-export environment variable lines.

Environment variable names already consumed by `regime_alerts.py`:
  G6_REGIME_MAE_DRIFT_RATIO_WARN / G6_REGIME_MAE_DRIFT_RATIO_CRIT
  G6_REGIME_NORM_DRIFT_RATIO_WARN / G6_REGIME_NORM_DRIFT_RATIO_CRIT
  G6_REGIME_COVERAGE_DRIFT_DROP_WARN / G6_REGIME_COVERAGE_DRIFT_DROP_CRIT
  G6_REGIME_DRIFT_WARN_PCTL / G6_REGIME_DRIFT_CRIT_PCTL
  G6_REGIME_COVERAGE_DRIFT_WARN_PCTL / G6_REGIME_COVERAGE_DRIFT_CRIT_PCTL

Run examples:
  python scripts/ml/calibrate_drift_thresholds.py --indices NIFTY,BANKNIFTY
  python scripts/ml/calibrate_drift_thresholds.py --indices NIFTY --warn-pctl 0.80 --crit-pctl 0.95 --min-count 30

If baselines are empty (counts < min-count) script exits with non-zero code unless --allow-empty is passed.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime
from typing import Dict, Any, List, Tuple

# Lazy imports (works when run within project root with PYTHONPATH including src)
try:
    from src.web.dashboard.rolling_mae import ensure_started, get_drift_baselines  # type: ignore
except Exception:
    ensure_started = None  # type: ignore
    get_drift_baselines = None  # type: ignore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Calibrate static drift thresholds from rolling baselines")
    p.add_argument("--indices", required=True, help="Comma-separated index list (e.g. NIFTY,BANKNIFTY)")
    p.add_argument("--warn-pctl", type=float, default=0.85, help="High-tail warn percentile for ratios (default 0.85)")
    p.add_argument("--crit-pctl", type=float, default=0.95, help="High-tail critical percentile for ratios (default 0.95)")
    p.add_argument("--coverage-warn-low-pctl", type=float, default=0.15, help="Lower-tail warn percentile for coverage delta (default 0.15)")
    p.add_argument("--coverage-crit-low-pctl", type=float, default=0.05, help="Lower-tail crit percentile for coverage delta (default 0.05)")
    p.add_argument("--min-count", type=int, default=20, help="Minimum samples required per metric to consider horizon (default 20)")
    p.add_argument("--artifact-dir", default="metrics/drift_baselines", help="Directory to write calibration artifact")
    p.add_argument("--allow-empty", action="store_true", help="Do not exit non-zero if insufficient data")
    p.add_argument("--json-only", action="store_true", help="Only write JSON artifact (suppress env export lines)")
    return p.parse_args()


def median_or_none(vals: List[float]) -> float | None:
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return None
    return statistics.median(sorted(vals))


def calibrate(args: argparse.Namespace) -> Dict[str, Any]:
    if get_drift_baselines is None:
        raise RuntimeError("rolling_mae.get_drift_baselines import failed; run from project root")
    if ensure_started is not None:
        try:
            ensure_started()  # starts background thread if not already
        except Exception:
            pass

    indices = [x.strip().upper() for x in args.indices.split(",") if x.strip()]
    baselines = get_drift_baselines()  # returns dict keyed by (INDEX, H)

    horizon_rows: List[Dict[str, Any]] = []
    mae_warn_candidates: List[float] = []
    mae_crit_candidates: List[float] = []
    norm_warn_candidates: List[float] = []
    norm_crit_candidates: List[float] = []
    cover_warn_candidates: List[float] = []
    cover_crit_candidates: List[float] = []

    warn_key = f"p{int(args.warn_pctl * 100)}"
    crit_key = f"p{int(args.crit_pctl * 100)}"
    cov_warn_key = f"p{int(args.coverage_warn_low_pctl * 100)}"
    cov_crit_key = f"p{int(args.coverage_crit_low_pctl * 100)}"

    for (idx, horizon), entry in sorted(baselines.items()):
        if idx not in indices:
            continue
        counts = entry.get("counts", {})
        mae_c = int(counts.get("mae", 0))
        norm_c = int(counts.get("norm", 0))
        cov_c = int(counts.get("coverage", 0))
        mae_pct = entry.get("mae_ratio", {})
        norm_pct = entry.get("norm_ratio", {})
        cov_pct = entry.get("coverage_delta", {})
        row: Dict[str, Any] = {
            "index": idx,
            "horizon": horizon,
            "counts": counts,
            "percentiles": {
                "mae_ratio": mae_pct,
                "norm_ratio": norm_pct,
                "coverage_delta": cov_pct,
            },
            "used": False,
        }
        # Only consider horizon if each metric meets min-count
        if mae_c >= args.min_count and norm_c >= args.min_count and cov_c >= args.min_count:
            mae_warn = mae_pct.get(warn_key)
            mae_crit = mae_pct.get(crit_key)
            norm_warn = norm_pct.get(warn_key)
            norm_crit = norm_pct.get(crit_key)
            cover_warn = cov_pct.get(cov_warn_key)  # coverage deltas are negative or small
            cover_crit = cov_pct.get(cov_crit_key)
            if mae_warn is not None:
                mae_warn_candidates.append(mae_warn)
            if mae_crit is not None:
                mae_crit_candidates.append(mae_crit)
            if norm_warn is not None:
                norm_warn_candidates.append(norm_warn)
            if norm_crit is not None:
                norm_crit_candidates.append(norm_crit)
            if cover_warn is not None:
                cover_warn_candidates.append(cover_warn)
            if cover_crit is not None:
                cover_crit_candidates.append(cover_crit)
            row["used"] = True
        horizon_rows.append(row)

    result: Dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "indices": indices,
        "warn_pctl": args.warn_pctl,
        "crit_pctl": args.crit_pctl,
        "coverage_warn_low_pctl": args.coverage_warn_low_pctl,
        "coverage_crit_low_pctl": args.coverage_crit_low_pctl,
        "min_count": args.min_count,
        "rows": horizon_rows,
        "aggregate": {},
    }

    agg = {
        "mae_warn": median_or_none(mae_warn_candidates),
        "mae_crit": median_or_none(mae_crit_candidates),
        "norm_warn": median_or_none(norm_warn_candidates),
        "norm_crit": median_or_none(norm_crit_candidates),
        "coverage_drop_warn": median_or_none(cover_warn_candidates),
        "coverage_drop_crit": median_or_none(cover_crit_candidates),
        "horizons_used": len([r for r in horizon_rows if r.get("used")]),
    }
    result["aggregate"] = agg
    return result


def main() -> int:
    args = parse_args()
    data = calibrate(args)
    agg = data.get("aggregate", {})

    # Decide exit on insufficiency
    if agg.get("horizons_used", 0) == 0:
        print("No horizons met min-count; insufficient data for calibration", file=sys.stderr)
        if not args.allow_empty:
            return 2

    # Prepare artifact
    artifact_dir = args.artifact_dir
    os.makedirs(artifact_dir, exist_ok=True)
    ts_tag = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(artifact_dir, f"calibrated_thresholds_{ts_tag}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    if not args.json_only and agg.get("horizons_used", 0) > 0:
        # Print export lines (shell-agnostic; adapt for PowerShell by using $env:VAR=...)
        print("# Export these to override static regime thresholds:")
        def fmt(v: Any) -> str:
            if v is None:
                return ""  # skip
            return f"{v:.6g}"  # concise
        lines: List[Tuple[str, Any]] = [
            ("G6_REGIME_DRIFT_WARN_PCTL", args.warn_pctl),
            ("G6_REGIME_DRIFT_CRIT_PCTL", args.crit_pctl),
            ("G6_REGIME_COVERAGE_DRIFT_WARN_PCTL", args.coverage_warn_low_pctl),
            ("G6_REGIME_COVERAGE_DRIFT_CRIT_PCTL", args.coverage_crit_low_pctl),
            ("G6_REGIME_MAE_DRIFT_RATIO_WARN", agg.get("mae_warn")),
            ("G6_REGIME_MAE_DRIFT_RATIO_CRIT", agg.get("mae_crit")),
            ("G6_REGIME_NORM_DRIFT_RATIO_WARN", agg.get("norm_warn")),
            ("G6_REGIME_NORM_DRIFT_RATIO_CRIT", agg.get("norm_crit")),
            ("G6_REGIME_COVERAGE_DRIFT_DROP_WARN", agg.get("coverage_drop_warn")),
            ("G6_REGIME_COVERAGE_DRIFT_DROP_CRIT", agg.get("coverage_drop_crit")),
        ]
        for name, val in lines:
            if val is None or val == "":
                continue
            print(f"{name}={fmt(val)}")
        print(f"# JSON artifact written: {out_path}")
    else:
        print(f"# JSON artifact written: {out_path}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
