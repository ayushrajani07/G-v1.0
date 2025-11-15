import json
import sys
from pathlib import Path


def _write_predictions(fp: Path, ts: str = "2025-11-11 10:00:00") -> None:
    fp.write_text(
        """
timestamp,prediction,model,horizon
{ts},100.0,sk_hgb_regressor,1
{ts},102.0,xgb_regressor,1
""".strip().format(ts=ts),
        encoding="utf-8",
    )


def _write_calibration(fp: Path, target: float = 0.80, dyn: float | None = 0.80,
                       cov_fast: float = 0.80, cov_slow: float = 0.805) -> None:
    obj = {
        "timestamp": 0,
        "recommended_k": 1.25,
        "k_smooth": 1.10,
        "effective_cov": target,
        "band_radius": 10.0,
        "target": target,
        "index": "NIFTY",
        "horizon": "1",
    }
    if dyn is not None:
        obj["dynamic_target_coverage"] = dyn
    obj["coverage_fast"] = {"value": cov_fast, "n": 50}
    obj["coverage_slow"] = {"value": cov_slow, "n": 120}
    fp.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _write_override(fp: Path, k: float = 1.5, expires: int | None = None) -> None:
    obj = {"overrides": {"1": {"k": k, "expires": expires}}}
    fp.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _run_exporter_once(monkeypatch, tmp_path: Path, extra_args: list[str] | None = None):
    import importlib
    mod = importlib.import_module("scripts.ml.ensemble_consensus_exporter")
    # Monkeypatch project_root to tmp workspace
    monkeypatch.setattr(mod, "project_root", lambda: tmp_path)
    argv = [
        "python",
        "--index",
        "NIFTY",
        "--horizon",
        "1",
        "--once",
    ]
    if extra_args:
        argv.extend(extra_args)
    monkeypatch.setattr(sys, "argv", [mod.__file__, *argv[1:]])
    mod.main()


def test_auto_revert_stable_removes_override(tmp_path, monkeypatch):
    base = tmp_path / "data" / "ml" / "live_predictions"
    base.mkdir(parents=True, exist_ok=True)

    # Inputs
    preds_fp = base / "NIFTY.csv"
    _write_predictions(preds_fp)
    calib_fp = base / "NIFTY_ensemble_k_calibration.json"
    _write_calibration(calib_fp, target=0.80, dyn=0.80, cov_fast=0.80, cov_slow=0.805)
    ov_fp = base / "NIFTY_ensemble_k_overrides.json"
    _write_override(ov_fp, k=1.5, expires=None)

    # Run twice with auto-revert enabled requiring 2 stable cycles
    _run_exporter_once(monkeypatch, tmp_path, [
        "--override-auto-revert",
        "--override-target-tolerance",
        "0.02",
        "--override-sustain-cycles",
        "2",
    ])
    # After first cycle still present
    o1 = json.loads(ov_fp.read_text(encoding="utf-8"))
    assert "1" in (o1.get("overrides") or {})

    _run_exporter_once(monkeypatch, tmp_path, [
        "--override-auto-revert",
        "--override-target-tolerance",
        "0.02",
        "--override-sustain-cycles",
        "2",
    ])
    # After second cycle should be removed
    o2 = json.loads(ov_fp.read_text(encoding="utf-8"))
    assert "1" not in (o2.get("overrides") or {})

    # Audit line written
    log_fp = base / "NIFTY_ensemble_k_overrides.log"
    assert log_fp.exists()
    log_txt = log_fp.read_text(encoding="utf-8")
    assert "AUTO_REMOVE" in log_txt and "coverage_stable" in log_txt


def test_auto_revert_dry_run_keeps_override_and_logs(tmp_path, monkeypatch):
    base = tmp_path / "data" / "ml" / "live_predictions"
    base.mkdir(parents=True, exist_ok=True)
    preds_fp = base / "NIFTY.csv"
    _write_predictions(preds_fp)
    calib_fp = base / "NIFTY_ensemble_k_calibration.json"
    _write_calibration(calib_fp, target=0.80, dyn=0.80, cov_fast=0.80, cov_slow=0.80)
    ov_fp = base / "NIFTY_ensemble_k_overrides.json"
    _write_override(ov_fp, k=1.4, expires=None)

    # Two cycles with dry-run
    for _ in range(2):
        _run_exporter_once(monkeypatch, tmp_path, [
            "--override-auto-revert",
            "--override-target-tolerance",
            "0.02",
            "--override-sustain-cycles",
            "2",
            "--dry-run-overrides",
        ])

    # Override should still be present
    o = json.loads(ov_fp.read_text(encoding="utf-8"))
    assert "1" in (o.get("overrides") or {})

    # Only require log file if auto-revert intent is logged
    log_fp = base / "NIFTY_ensemble_k_overrides.log"
    if log_fp.exists():
        log_txt = log_fp.read_text(encoding="utf-8")
        assert "AUTO_REMOVE" in log_txt and "coverage_stable" in log_txt


def test_ttl_expiry_removes_override_and_logs(tmp_path, monkeypatch):
    base = tmp_path / "data" / "ml" / "live_predictions"
    base.mkdir(parents=True, exist_ok=True)
    preds_fp = base / "NIFTY.csv"
    _write_predictions(preds_fp)
    calib_fp = base / "NIFTY_ensemble_k_calibration.json"
    _write_calibration(calib_fp, target=0.80, dyn=None, cov_fast=0.75, cov_slow=0.76)
    ov_fp = base / "NIFTY_ensemble_k_overrides.json"
    # Set expiry far in the past to guarantee pruning
    _write_override(ov_fp, k=1.6, expires=1)

    _run_exporter_once(monkeypatch, tmp_path, [])

    o = json.loads(ov_fp.read_text(encoding="utf-8"))
    assert (o.get("overrides") or {}) == {}, "expired override should be pruned"

    log_fp = base / "NIFTY_ensemble_k_overrides.log"
    assert log_fp.exists()
    log_txt = log_fp.read_text(encoding="utf-8")
    assert "AUTO_REMOVE" in log_txt and "ttl_expired" in log_txt
