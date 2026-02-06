# Tooling & Automation

## Scope
CLI utilities, maintenance scripts, CI automation, local developer workflows.

## Primary code
- `src/tools/`
- `scripts/`
- `tools/`
- `.github/`

## Signals (from generated stats)
- `src/tools`: ~1.7k LOC; ~63 `except Exception` occurrences; relatively high `noqa` usage.

## Maintainability risks
- Scripts grow organically and encode “tribal knowledge”.
- Tools often skip typing/linting and drift from production conventions.

## Improvements
- Promote stable scripts to documented CLIs with `--help` and tests where valuable.
- Keep scripts small and reuse library code from `src/`.
- Document supported workflows (golden paths) and retire duplicates.
