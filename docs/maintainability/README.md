# Maintainability & Clarity Audit

This section documents a long-term maintainability review of the codebase.

## What this is
- A broad module decomposition (conceptual boundaries, not just folders)
- Module-by-module audit notes: risks, clarity gaps, and concrete refactors
- A prioritized backlog of improvements with suggested sequencing

## Quick links
- Module map: [MODULE_MAP.md](MODULE_MAP.md)
- Cross-module backlog: [BACKLOG.md](BACKLOG.md)
- Module audits: [modules/](modules/)

## Supporting artifacts (generated)
- Baseline stats per `src/*` module (LOC, `except Exception`, `type: ignore`, etc):
  - `artifacts/maintainability/module_stats.md`
  - `artifacts/maintainability/module_stats.json`

- File hotspot rankings (largest files / most catch-all exceptions / most type ignores):
  - `artifacts/maintainability/file_hotspots.md`
  - `artifacts/maintainability/file_hotspots.json`

- Coverage risk hotspots (requires `coverage.xml`):
  - `artifacts/maintainability/coverage_hotspots.txt`

- Dead code scan reports:
  - `docs/dead_code.md`
  - `tools/dead_code_report.json`

To regenerate:
```powershell
python scripts/run_maintainability_suite.py --repo-root .

# If you also want coverage hotspots and don't have coverage.xml yet:
python scripts/run_maintainability_suite.py --repo-root . --with-coverage

# Or run individual steps:
python scripts/maintainability_audit.py --repo-root .
python -m scripts.cleanup.dead_code_scan  # requires vulture (see requirements.txt)
python scripts/coverage_hotspots.py --xml coverage.xml --prefix src/ --top 25
```
