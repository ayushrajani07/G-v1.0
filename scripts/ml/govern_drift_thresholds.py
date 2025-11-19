#!/usr/bin/env python
"""Governance scheduler for drift thresholds: calibrate -> validate -> promote.

Workflow:
1) Run calibration for given indices to produce a new artifact in metrics/drift_baselines.
2) Run stability validation across artifacts; compare latest vs prior median.
3) If stable and horizons_used >= min, and guard-rails pass, write a signed manifest
   to metrics/drift_manifests and optionally apply env overrides (update .env).

Exit codes:
  0 success (promoted or noop stable) | 2 insufficient | 3 unstable | 4 guard-rail reject

Notes:
- Schedule externally (Windows Task Scheduler/Cron) to run daily/hourly.
- For PowerShell, you can set env via token_manager.update_env_file
  which updates .env and in-memory env for the current process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, Tuple

from scripts.ml.calibrate_drift_thresholds import calibrate as run_calibration, parse_args as parse_calib_args  # type: ignore
from scripts.ml.validate_drift_threshold_stability import load_artifacts, compute_report  # type: ignore
try:  # Optional Prometheus client for emitting governance metrics
    from prometheus_client import Gauge as _PG  # type: ignore
except Exception:  # pragma: no cover
    _PG = None  # type: ignore

# Lazy metric holders (module-level singletons) – created if prometheus_client available
_g_shift = None  # relative shift per key
_g_promotable = None  # 1 if promotable else 0
_g_violations = None  # count of violations latest evaluation
_g_horizons_used = None  # horizons_used in latest aggregate

try:
    from src.tools.token_manager import update_env_file  # type: ignore
except Exception:  # pragma: no cover
    def update_env_file(key, value):  # type: ignore
        # best-effort local .env update
        env_file = ".env"
        lines: list[str] = []
        if os.path.isfile(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.startswith(f"{key}="):
                        lines.append(line.rstrip("\n"))
        lines.append(f"{key}={value}")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        try:
            os.environ[key] = str(value)
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Govern drift thresholds: calibrate, validate, promote")
    p.add_argument("--indices", required=True, help="Comma-separated index list, e.g. NIFTY,BANKNIFTY")
    p.add_argument("--artifact-dir", default="metrics/drift_baselines", help="Calibration artifact directory")
    p.add_argument("--manifest-dir", default="metrics/drift_manifests", help="Manifest output directory")
    p.add_argument("--min-count", type=int, default=20, help="Minimum samples per metric per horizon (calibration)")
    p.add_argument("--min-horizons-to-promote", type=int, default=3, help="Minimum horizons used required to promote")
    p.add_argument("--warn-pctl", type=float, default=0.85, help="High-tail percentile for warn thresholds")
    p.add_argument("--crit-pctl", type=float, default=0.95, help="High-tail percentile for crit thresholds")
    p.add_argument("--coverage-warn-low-pctl", type=float, default=0.15, help="Lower-tail percentile for coverage warn")
    p.add_argument("--coverage-crit-low-pctl", type=float, default=0.05, help="Lower-tail percentile for coverage crit")
    p.add_argument("--max-percent-shift", type=float, default=0.15, help="Max allowed relative shift vs prior median")
    p.add_argument("--apply-env", action="store_true", help="Apply promoted thresholds to .env (and env) if accepted")
    p.add_argument("--dry-run", action="store_true", help="Compute and write manifest only; do not apply env")
    p.add_argument("--json", action="store_true", help="Print JSON result")
    p.add_argument("--rollback-on-critical", action="store_true", help="Rollback to previous manifest if any relative shift >= rollback-threshold")
    p.add_argument("--rollback-threshold", type=float, default=0.25, help="Relative shift fraction triggering rollback (e.g. 0.25 = 25%)")
    return p.parse_args()


def guard_rails(agg: Dict[str, Any]) -> Tuple[bool, str]:
    """Basic sanity constraints to avoid extreme promotions."""
    try:
        mw = float(agg.get("mae_warn"))
        mc = float(agg.get("mae_crit"))
        nw = float(agg.get("norm_warn"))
        nc = float(agg.get("norm_crit"))
        cw = float(agg.get("coverage_drop_warn"))
        cc = float(agg.get("coverage_drop_crit"))
    except Exception:
        return False, "missing_or_non_numeric_thresholds"
    if not (1.05 <= mw <= 2.5):
        return False, "mae_warn_out_of_range"
    if not (mw <= mc <= 3.0):
        return False, "mae_crit_out_of_range"
    if not (1.05 <= nw <= 2.5):
        return False, "norm_warn_out_of_range"
    if not (nw <= nc <= 3.0):
        return False, "norm_crit_out_of_range"
    if not (-50.0 <= cw <= 0.0):
        return False, "coverage_drop_warn_out_of_range"
    if not (cw - 20.0 <= cc <= 0.0):
        return False, "coverage_drop_crit_out_of_range"
    return True, "ok"


def sha256_json(obj: Dict[str, Any]) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def main() -> int:
    args = parse_args()
    os.makedirs(args.artifact_dir, exist_ok=True)
    os.makedirs(args.manifest_dir, exist_ok=True)

    # Step 1: Calibration (reusing calibration module directly)
    calib_ns = argparse.Namespace(
        indices=args.indices,
        warn_pctl=args.warn_pctl,
        crit_pctl=args.crit_pctl,
        coverage_warn_low_pctl=args.coverage_warn_low_pctl,
        coverage_crit_low_pctl=args.coverage_crit_low_pctl,
        min_count=args.min_count,
        artifact_dir=args.artifact_dir,
        allow_empty=False,
        json_only=True,
    )
    calib = run_calibration(calib_ns)

    # Write artifact file with timestamp for governance traceability
    ts_tag = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    artifact_path = os.path.join(args.artifact_dir, f"calibrated_thresholds_{ts_tag}.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2, sort_keys=True)

    # Step 2: Stability validation
    artifacts = load_artifacts(args.artifact_dir)
    report = compute_report(artifacts, args.max_percent_shift, args.min_horizons_to_promote)

    status = report.get("status")
    agg = calib.get("aggregate", {})
    promotable = (
        status == "stable"
        and int(agg.get("horizons_used", 0)) >= int(args.min_horizons_to_promote)
    )

    reason = "stable" if promotable else status or "unknown"
    if promotable:
        ok, guard_reason = guard_rails(agg)
        if not ok:
            promotable = False
            reason = f"guard_rails:{guard_reason}"

    # Step 3: Manifest write (+ optional env apply)
    prev_latest = None
    latest_path = os.path.join(args.manifest_dir, "latest.json")
    if os.path.isfile(latest_path):
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                prev = json.load(f)
            prev_latest = prev.get("manifest_file") or "latest.json"
        except Exception:
            prev_latest = None

    manifest = {
        "version": 1,
        "promoted_at": datetime.utcnow().isoformat() + "Z",
        "indices": [x.strip().upper() for x in args.indices.split(",") if x.strip()],
        "horizons_used": agg.get("horizons_used", 0),
        "percentiles": {
            "warn_pctl": args.warn_pctl,
            "crit_pctl": args.crit_pctl,
            "coverage_warn_low_pctl": args.coverage_warn_low_pctl,
            "coverage_crit_low_pctl": args.coverage_crit_low_pctl,
        },
        "thresholds": {
            "G6_REGIME_MAE_DRIFT_RATIO_WARN": agg.get("mae_warn"),
            "G6_REGIME_MAE_DRIFT_RATIO_CRIT": agg.get("mae_crit"),
            "G6_REGIME_NORM_DRIFT_RATIO_WARN": agg.get("norm_warn"),
            "G6_REGIME_NORM_DRIFT_RATIO_CRIT": agg.get("norm_crit"),
            "G6_REGIME_COVERAGE_DRIFT_DROP_WARN": agg.get("coverage_drop_warn"),
            "G6_REGIME_COVERAGE_DRIFT_DROP_CRIT": agg.get("coverage_drop_crit"),
        },
        "stability": {
            "status": status,
            "violations": report.get("violations", 0),
            "artifact_count": report.get("artifact_count", 0),
            "latest_artifact": report.get("latest_file"),
        },
        "source_artifact": artifact_path,
        "previous_manifest": prev_latest,
        "promoted": bool(promotable),
        "reason": reason,
    }
    manifest["signature"] = sha256_json(manifest)

    mf_name = f"manifest_{ts_tag}.json"
    mf_path = os.path.join(args.manifest_dir, mf_name)
    with open(mf_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    # Update latest pointer file for quick access
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump({"manifest_file": mf_name, "signature": manifest["signature"]}, f, indent=2, sort_keys=True)

    applied = False
    rolled_back = False
    rollback_source = None

    # Automatic rollback path (critical shift) BEFORE promotion apply
    if args.rollback_on_critical and report.get('keys'):
        try:
            critical = any(
                isinstance(e.get('relative_shift'), (int, float)) and e.get('relative_shift') >= args.rollback_threshold
                for e in report['keys']
            )
        except Exception:
            critical = False
        if critical and prev_latest:
            prev_path = os.path.join(args.manifest_dir, prev_latest)
            try:
                with open(prev_path, 'r', encoding='utf-8') as pf:
                    prev_manifest = json.load(pf)
                prev_thresholds = prev_manifest.get('thresholds', {})
                if prev_thresholds:
                    if not args.dry_run and args.apply_env:
                        for k, v in prev_thresholds.items():
                            if v is None:
                                continue
                            update_env_file(k, f"{float(v):.6g}")
                    rolled_back = True
                    rollback_source = prev_latest
                    manifest['promoted'] = False
                    manifest['reason'] = f"rollback_triggered(relative_shift>={args.rollback_threshold})"
                    reason = manifest['reason']
            except Exception:
                pass

    if not rolled_back and promotable and not args.dry_run and args.apply_env:
        for k, v in manifest["thresholds"].items():
            if v is None:
                continue
            update_env_file(k, f"{float(v):.6g}")
        applied = True

    result = {
        "status": status,
        "promotable": promotable,
        "applied": applied,
        "manifest": mf_path,
        "artifact": artifact_path,
        "reason": reason,
        "rolled_back": rolled_back,
        "rollback_source": rollback_source,
        "promoted": manifest.get("promoted", False),
    }

    # --- Metrics emission (best-effort) ---------------------------------
    if _PG:
        global _g_shift, _g_promotable, _g_violations, _g_horizons_used
        try:
            if _g_shift is None:
                _g_shift = _PG(
                    'g6_drift_threshold_relative_shift',
                    'Relative shift of latest calibrated drift threshold vs historical median',
                    ['key']
                )
            if _g_promotable is None:
                _g_promotable = _PG(
                    'g6_drift_threshold_promotable',
                    '1 if latest calibration passed stability & guard rails',
                    []
                )
            if _g_violations is None:
                _g_violations = _PG(
                    'g6_drift_threshold_stability_violations',
                    'Count of threshold keys exceeding max_percent_shift in latest evaluation',
                    []
                )
            if _g_horizons_used is None:
                _g_horizons_used = _PG(
                    'g6_drift_threshold_horizons_used',
                    'Horizons used count in latest aggregate calibration',
                    []
                )
            # Populate
            for entry in report.get('keys', []):
                k = entry.get('key')
                rs = entry.get('relative_shift')
                if k and isinstance(rs, (int, float)) and _g_shift:
                    _g_shift.labels(k).set(rs)
            if _g_promotable:
                _g_promotable.set(1 if promotable else 0)
            if _g_violations:
                _g_violations.set(report.get('violations', 0))
            if _g_horizons_used:
                try:
                    _g_horizons_used.set(float(agg.get('horizons_used', 0) or 0))
                except Exception:
                    _g_horizons_used.set(0)
        except Exception:
            pass  # silent failure; metrics are optional

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"status={status} promotable={promotable} applied={applied} reason={reason}")
        print(f"manifest={mf_path}")
        print(f"artifact={artifact_path}")

    if status == "unstable":
        return 3
    if status and status.startswith("insufficient"):
        return 2
    if not promotable and reason.startswith("guard_rails:"):
        return 4
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
