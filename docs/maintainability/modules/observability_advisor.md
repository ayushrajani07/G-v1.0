# Observability & Advisor

## Scope
Metrics registry, health checks, advisor engine, summary models and status surface.

## Primary code
- `src/metrics/`
- `src/observability/`
- `src/health/`
- `src/summary/`
- `src/advisor/`

## Signals (from generated stats)
- `src/metrics`: ~9.6k LOC; low `except Exception` count (~15) but **high `type: ignore` (~359)**.
- `src/summary`: ~2.5k LOC; ~47 `except Exception` occurrences and some TODO/FIXME.

## Hotspot files (good first refactor targets)
- `src/metrics/metrics.py` (high `type: ignore` density)

## Maintainability risks
- Type ignores can hide API mismatches; metrics code is often cross-cutting and hard to refactor.

## Improvements
- Decide where strict typing matters (public registry and metric factories) and tighten there.
- Provide a small “metrics facade” API; keep direct imports internal.
- Keep advisor plugins isolated and pure where possible (IO through a context interface).
