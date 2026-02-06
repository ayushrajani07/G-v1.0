# Presentation Surfaces (Web / Panels / Summary UI)

## Scope
Web API endpoints and dashboard surfaces, panels generation/integrity, UI utilities.

## Primary code
- `src/web/` (API + dashboard)
- `src/panels/`
- `scripts/summary/` (app / renderers)
- `src/ui_enhanced/`

## Signals (from generated stats)
- `src/web`: ~10.4k LOC; **~426** `except Exception` occurrences.
- `src/panels`: ~1.1k LOC; ~26 `except Exception` occurrences.

## Hotspot files (good first refactor targets)
- `src/web/dashboard/routes/path_forecast/` (router package; formerly `path_forecast.py` monolith)
- `src/web/dashboard/routes/ml.py` (very large; high catch-all density)
- `src/web/dashboard/app.py`
- `src/web/dashboard/core/csv_io.py`

## Maintainability risks
- Web routes can become “catch-all + 200 OK” with hidden failures.
- Surface area creep: debug routes and internal endpoints mix.

## Improvements
- Centralize error-to-response mapping (typed errors → status codes) and test it.
- Separate route handlers (HTTP) from service logic (pure functions / small services).
- Document the public API surface and versioning expectations.
