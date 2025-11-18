#!/usr/bin/env python
"""Validate stability of calibrated drift thresholds over time.

This harness inspects previously generated calibration artifacts produced by
`scripts/ml/calibrate_drift_thresholds.py` (files named `calibrated_thresholds_*.json`)
under the artifact directory (default: metrics/drift_baselines).

It computes relative shifts for each aggregate threshold between the latest
artifact and the median of all prior artifacts. If any shift exceeds the
configured maximum percentage, the script exits non‑zero (default 3).

Keys validated (when present):
  mae_warn, mae_crit, norm_warn, norm_crit, coverage_drop_warn, coverage_drop_crit

Exit codes:
  0 = stable or insufficient history allowed
  2 = insufficient artifacts (needs >=2) and not --allow-insufficient
  3 = instability detected (shift > max-percent-shift)

Examples:
  python scripts/ml/validate_drift_threshold_stability.py
  python scripts/ml/validate_drift_threshold_stability.py --artifact-dir metrics/drift_baselines --max-percent-shift 0.1
  python scripts/ml/validate_drift_threshold_stability.py --min-horizons-used 2 --allow-insufficient

PowerShell CI usage (treat instability as warning):
  python scripts/ml/validate_drift_threshold_stability.py || echo "Drift threshold instability detected"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from typing import Any, Dict, List

NAME_PATTERN = re.compile(r"calibrated_thresholds_\d{8}_\d{6}\.json$")

VALID_KEYS = [
    "mae_warn",
    "mae_crit",
    "norm_warn",
    "norm_crit",
    "coverage_drop_warn",
    "coverage_drop_crit",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate stability of calibrated drift thresholds")
    p.add_argument("--artifact-dir", default="metrics/drift_baselines", help="Directory containing calibration artifacts")
    p.add_argument("--max-percent-shift", type=float, default=0.15, help="Max allowed relative shift vs historical median (default 0.15 = 15%)")
    p.add_argument("--allow-insufficient", action="store_true", help="Return 0 if insufficient artifacts")
    p.add_argument("--min-horizons-used", type=int, default=1, help="Minimum horizons_used in latest artifact required for validation")
    p.add_argument("--json", action="store_true", help="Output JSON report instead of human text")
    return p.parse_args()


def load_artifacts(path: str) -> List[Dict[str, Any]]:
    if not os.path.isdir(path):
        return []
    files = [f for f in os.listdir(path) if NAME_PATTERN.search(f)]
    files.sort()  # chronological due to timestamp naming
    out: List[Dict[str, Any]] = []
    for f in files:
        p = os.path.join(path, f)
        try:
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            data["__file"] = p
            out.append(data)
        except Exception:
            continue
    return out


def rel_shift(latest: float, baseline: float) -> float | None:
    try:
        if baseline == 0:
            return None
        return abs(latest - baseline) / abs(baseline)
    except Exception:
        return None


def compute_report(artifacts: List[Dict[str, Any]], max_pct: float, min_horizons: int) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "artifact_count": len(artifacts),
        "status": "pending",
        "max_percent_shift": max_pct,
        "keys": [],
        "latest_file": None,
        "violations": 0,
    }
    if len(artifacts) < 2:
        report["status"] = "insufficient";
        return report
    latest = artifacts[-1]
    prev = artifacts[:-1]
    latest_agg = latest.get("aggregate", {})
    report["latest_file"] = latest.get("__file")
    if int(latest_agg.get("horizons_used", 0)) < min_horizons:
        report["status"] = "insufficient_horizons"
        return report
    for key in VALID_KEYS:
        latest_val = latest_agg.get(key)
        if latest_val is None:
            continue
        prev_vals = [a.get("aggregate", {}).get(key) for a in prev if isinstance(a.get("aggregate"), dict)]
        prev_vals = [v for v in prev_vals if isinstance(v, (int, float))]
        median_prev = statistics.median(prev_vals) if prev_vals else None
        if median_prev is None:
            continue
        shift = rel_shift(float(latest_val), float(median_prev))
        violation = bool(shift is not None and shift > max_pct)
        if violation:
            report["violations"] += 1
        report["keys"].append({
            "key": key,
            "latest": latest_val,
            "median_prev": median_prev,
            "relative_shift": shift,
            "violation": violation,
        })
    report["status"] = "stable" if report["violations"] == 0 else "unstable"
    return report


def main() -> int:
    args = parse_args()
    artifacts = load_artifacts(args.artifact_dir)
    report = compute_report(artifacts, args.max_percent_shift, args.min_horizons_used)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Artifacts: {report['artifact_count']}  Latest: {report.get('latest_file')}  Status: {report['status']}")
        for entry in report.get("keys", []):
            print("- {key}: latest={latest:.4g} median_prev={median_prev:.4g} shift={shift:.2%}{flag}".format(
                key=entry['key'], latest=entry['latest'], median_prev=entry['median_prev'],
                shift=(entry['relative_shift'] or 0.0), flag=" !" if entry['violation'] else ""))
        if report['status'] == 'unstable':
            print(f"Threshold instability detected (> {args.max_percent_shift:.0%} shift)")
        elif report['status'].startswith('insufficient'):
            print("Insufficient data for stability evaluation")
    # Determine exit code
    if report['status'] == 'unstable':
        return 3
    if report['status'].startswith('insufficient') and not args.allow_insufficient:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
