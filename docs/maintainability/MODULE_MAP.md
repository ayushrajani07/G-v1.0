# Broad Module Map

This repo has many `src/*` packages; this document groups them into *broad modules* with clearer long-term boundaries.

## Dependency direction (target architecture)
Recommended dependency flow (outer layers may depend on inner layers, not vice-versa):

1. **Types & Contracts** (`src/types`, `src/interfaces`, `src/schema`, selected `src/domain`)
2. **Core Utilities** (`src/utils`, `src/errors`, `src/security`)
3. **Infrastructure** (**metrics**, **storage**, **web surface adapters**) (`src/metrics`, `src/storage`, `src/web`)
4. **Business Logic** (**collection**, **providers**, **analytics/ML**) (`src/collectors`, `src/broker`, `src/providers`, `src/analytics`, `src/path_forecast`, `src/ml`)
5. **Orchestration / Entry** (`src/orchestrator`, `src/unified_main.py`, scripts in `scripts/`)

Notes:
- The intent is to *reduce cyclic imports* and eliminate “facade as band-aid” patterns over time.
- Cross-cutting concerns (logging, error taxonomy, tracing) should live in **Core Utilities**.

## Broad modules

| Broad module | Primary paths | Responsibilities |
|---|---|---|
| Runtime & Orchestration | `src/orchestrator`, `src/runtime`, `src/lifecycle`, `src/unified_main.py`, `scripts/run_orchestrator_loop.py` | Bootstrap, interval loop, lifecycle, graceful shutdown, feature toggles |
| Collection Pipeline | `src/collectors`, `src/collector`, `src/bus`, `src/streaming`, `src/events`, `src/filters` | Per-cycle orchestration, data fetch/enrich/validate/persist, event production |
| Providers & Brokerage | `src/broker`, `src/providers`, `src/provider`, `src/tools/token_*` | External API access, token/auth, provider adapters, failover/fallback |
| Analytics & Forecasting | `src/analytics`, `src/path_forecast`, `src/ml`, `src/adaptive` | Greeks/IV/PCR analytics, path forecasting, ANN tooling, adaptive gating |
| Persistence & Data Access | `src/storage`, `src/data_access`, `src/column_store` | CSV/Influx persistence, query/readback, retention, column-store integration |
| Observability & Advisor | `src/metrics`, `src/observability`, `src/health`, `src/summary`, `src/advisor` | Metrics registry, health endpoints, dashboards/panels inputs, advisory engine |
| Presentation Surfaces | `src/web`, `src/panels`, `src/ui_enhanced`, `scripts/summary/*` | Web API routes, dashboard server, panels generation/integrity, summary UI |
| Configuration & Governance | `src/config`, `src/schema`, tests in `tests/config`, docs in `docs/` | Config loading/validation, env conventions, doc/test governance |
| Tooling & Automation | `src/tools`, `scripts/`, `tools/`, `.github/` | CLIs, maintenance scripts, CI automation, local workflows |

## What “done” looks like
For each broad module we want:
- A clear “public API” (entrypoints and stable types)
- A small set of outbound dependencies (enforced by convention/tests)
- Module-level docs: purpose, key flows, extension points, invariants
- A small error taxonomy: known failures are typed and consistently handled
