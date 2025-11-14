from __future__ import annotations

import os
import sys
import time
import traceback
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from xml.etree import ElementTree as ET


def _ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def _print_summary_from_junit(junit_path: str, exit_code: int) -> None:
    try:
        tree = ET.parse(junit_path)
        root = tree.getroot()
        # Support either <testsuite> root or <testsuites>/<testsuite>
        ts = root
        if ts.tag == "testsuites":
            suites = list(ts)
            ts = suites[0] if suites else ts
        total = int(ts.attrib.get("tests", 0))
        failures = int(ts.attrib.get("failures", 0))
        errors = int(ts.attrib.get("errors", 0))
        skipped = int(ts.attrib.get("skipped", 0))
        # time attr can be float seconds
        duration = ts.attrib.get("time", "0")
        # Derive passed
        passed = max(total - failures - errors - skipped, 0)
        print(
            f"Pytest core-only summary: {passed} passed, {failures} failed, {errors} errors, {skipped} skipped; exit {exit_code}"
        )
        # Include duration if present
        if duration and duration != "0":
            try:
                d = float(duration)
                print(f"Duration: {d:.2f}s")
            except Exception:
                pass
    except Exception:
        # Fallback minimal notice
        print(f"Pytest finished with exit {exit_code} (failed to parse JUnit at {junit_path})")


def main() -> None:
    try:
        import pytest  # type: ignore
    except Exception as e:  # pragma: no cover
        print(f"ERROR: pytest is not installed or failed to import: {e}")
        sys.exit(2)

    # Normalize environment for deterministic metrics spec behavior:
    # - Ensure no metric groups are force-disabled/enabled by host env
    # - Avoid egress freeze impacting metrics surface
    for k in (
        "G6_DISABLE_METRIC_GROUPS",
        "G6_METRICS_DISABLE_METRIC_GROUPS",
        "G6_ENABLE_METRIC_GROUPS",
        "G6_METRICS_ENABLE_METRIC_GROUPS",
        "G6_EGRESS_FROZEN",
    ):
        if k in os.environ:
            os.environ.pop(k, None)

    # Where to capture output; default to repo root file
    out_path = os.environ.get("PYTEST_CAPTURE_FILE", os.path.join(os.getcwd(), "pytest_core_out.txt"))
    artifacts_dir = os.path.join(os.getcwd(), "artifacts")
    _ensure_dir(artifacts_dir)
    junit_path = os.path.join(artifacts_dir, "pytest_core_junit.xml")

    # Core-only, parallel run excluding ML tests
    args = [
        "-n",
        "auto",
        "--dist=loadgroup",
        "-m",
        "not serial",
        "--ignore=tests/ml",
        "-r",
        "a",
        "-vv",
        "--junitxml",
        junit_path,
    ]

    # Write only to file (clear, deterministic). For live console echo, we could tee, but keeping simple here.
    with open(out_path, "w", encoding="utf-8", buffering=1) as f, ExitStack() as stack:
        stack.enter_context(redirect_stdout(f))
        stack.enter_context(redirect_stderr(f))
        rc = pytest.main(args)

    # Emit a concise human summary to console and attempt artifact collection on failure
    _print_summary_from_junit(junit_path, rc)
    print(f"Captured full output to: {out_path}")
    print(f"JUnit report: {junit_path}")

    if rc != 0:
        try:
            # Attempt to collect artifacts for convenience
            try:
                # Try package-style import first (if scripts/ is a package)
                from scripts.dev.collect_pytest_artifacts import collect  # type: ignore
            except Exception:
                # Fallback: load module by path without package requirement
                import importlib.util

                module_path = os.path.join(os.getcwd(), "scripts", "dev", "collect_pytest_artifacts.py")
                spec = importlib.util.spec_from_file_location("collect_pytest_artifacts", module_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
                    collect = getattr(mod, "collect")  # type: ignore[assignment]
                else:
                    raise RuntimeError("Unable to load collect_pytest_artifacts module")

            zip_path = collect(defaults=True)
            if zip_path:
                print(f"Artifacts collected at: {zip_path}")
        except SystemExit:
            raise
        except Exception:
            # Best-effort only; do not mask test exit code
            print("Artifact collection failed:")
            traceback.print_exc()

    sys.exit(rc)


if __name__ == "__main__":
    main()
