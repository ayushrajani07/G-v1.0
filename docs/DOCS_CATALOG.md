# Docs Catalog (Migration Helper)

Purpose: lightweight index for where docs live while the repo is being reorganized.

## Canonical categories

- **Architecture**: `docs/architecture/`
- **Operations**: `docs/operations/`
- **Runbooks**: `docs/runbooks/`
- **Development**: `docs/development/`
- **Reference**: `docs/reference/`

## Redirected root docs (moved)

When a root-level doc is moved, a stub file remains at the old path pointing to the new canonical location.

- DEPLOYMENT_GUIDE.md -> docs/operations/deployment/DEPLOYMENT_GUIDE.md
- OPERATOR_MANUAL.md -> docs/operations/OPERATOR_MANUAL.md
- RESTART_GUIDE_WINDOWS.md -> docs/operations/runtime/RESTART_GUIDE_WINDOWS.md
- DEVELOPMENT_GUIDELINES.md -> docs/development/DEVELOPMENT_GUIDELINES.md
- GITHUB_SETUP.md -> docs/development/GITHUB_SETUP.md
- TESTING.md -> docs/development/testing/TESTING.md
- TESTS_RUNBOOK.md -> docs/development/testing/TESTS_RUNBOOK.md

## Archived / historical docs (moved)

- README_2025-10-21.md -> docs/legacy/readmes/README_2025-10-21.md
- README_COMPREHENSIVE.md -> docs/legacy/readmes/README_COMPREHENSIVE.md
- README_CONSOLIDATED_DRAFT.md -> docs/legacy/readmes/README_CONSOLIDATED_DRAFT.md
- README_web_dashboard.md -> docs/legacy/readmes/README_web_dashboard.md
- README_HYBRID_EXPORTER.md -> docs/legacy/readmes/README_HYBRID_EXPORTER.md
- README_QUANTILE_EXPORTER.md -> docs/legacy/readmes/README_QUANTILE_EXPORTER.md

## Legacy archive redirects

- archive/readmes/* -> docs/legacy/readmes/* (redirect stubs)
