from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  cwd: {cwd}\n"
            f"  exit: {proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run maintainability artifacts generation (module stats, dead-code report, coverage hotspots)"
    )
    ap.add_argument("--repo-root", default=".")
    ap.add_argument(
        "--with-coverage",
        action="store_true",
        help="Generate coverage.xml via pytest --cov before running coverage_hotspots",
    )
    ap.add_argument(
        "--dead-code-min-confidence",
        type=int,
        default=60,
        help="Vulture min confidence for dead-code scan (default 60)",
    )
    ap.add_argument(
        "--skip-dead-code",
        action="store_true",
        help="Skip dead code scan step",
    )
    ap.add_argument(
        "--skip-coverage-hotspots",
        action="store_true",
        help="Skip coverage hotspots step",
    )
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if not (repo_root / "src").exists():
        raise SystemExit(f"src dir not found under repo root: {repo_root}")

    # 1) Maintainability audit -> artifacts/maintainability/*
    _run(
        [
            sys.executable,
            "scripts/maintainability_audit.py",
            "--repo-root",
            str(repo_root),
        ],
        cwd=repo_root,
    )

    # 2) Dead code scan -> tools/dead_code_report.json + docs/dead_code.md
    if not args.skip_dead_code:
        _run(
            [
                sys.executable,
                "-m",
                "scripts.cleanup.dead_code_scan",
                "--min-confidence",
                str(int(args.dead_code_min_confidence)),
            ],
            cwd=repo_root,
        )

    # 3) Coverage hotspots -> artifacts/maintainability/coverage_hotspots.txt
    if not args.skip_coverage_hotspots:
        if args.with_coverage:
            _run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--cov=src",
                    "--cov-report=xml",
                    "--tb=short",
                    "-q",
                ],
                cwd=repo_root,
            )

        cov_xml = repo_root / "coverage.xml"
        if cov_xml.exists():
            proc = subprocess.run(
                [
                    sys.executable,
                    "scripts/coverage_hotspots.py",
                    "--xml",
                    str(cov_xml),
                    "--prefix",
                    "src/",
                    "--top",
                    "25",
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    "coverage hotspots failed:\n"
                    f"exit: {proc.returncode}\n"
                    f"stdout:\n{proc.stdout}\n"
                    f"stderr:\n{proc.stderr}\n"
                )
            out_path = repo_root / "artifacts" / "maintainability" / "coverage_hotspots.txt"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(proc.stdout, encoding="utf-8")
        else:
            print(
                "[maintainability-suite] coverage.xml not found; skipping coverage hotspots (run with --with-coverage)",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
