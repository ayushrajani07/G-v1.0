# Maintainability Backlog (Cross-Module)

This is a *prioritized*, long-term backlog focused on maintainability and clarity.

The ordering is biased toward: reducing debugging time, shrinking cyclic coupling, and making behavior easier to reason about.

## P0 — Biggest ROI / unblock future refactors

1. **Exception taxonomy + policy (reduce blanket `except Exception`)**
   - Target first: `src/collectors`, `src/web`, `src/utils`, `src/broker`, `src/storage`.
   - Replace “catch-all then continue” with explicit categories:
     - *Transient provider errors* (retry/backoff)
     - *Validation/data-quality errors* (quarantine/drop + metrics)
     - *Invariants/bugs* (raise fast; fail cycle)
   - Centralize policy in `src/errors/*` and route through one facade.

2. **Boundary tightening: isolate Orchestration from Business Logic**
   - Make `src/orchestrator` call a small, stable API (e.g., `collectors.run_cycle(...)`).
   - Avoid orchestration reaching into internal helpers across packages.

3. **Provider surface unification (`broker` vs `provider(s)`)**
   - Decide the canonical abstraction: one “Provider Protocol” and one factory.
   - Deprecate parallel entrypoints and adapters over time.

## P1 — Reduce cognitive load

4. **Module entrypoint docs (one-pager per broad module)**
   - Add “start here” entrypoints, extension points, and invariants.

5. **Type hygiene plan (reduce `type: ignore`)**
   - Metrics currently carries a high `type: ignore` count; decide where types matter.
   - Prefer Protocols + typed wrappers at boundaries, rather than local ignores.

6. **Naming + layering conventions**
   - Standardize suffixes (`*Facade`, `*Service`, `*Registry`, `*Sink`) and when each is allowed.
   - Prefer `domain/*` for pure models and keep IO out of it.

## P2 — Operational clarity

7. **Configuration lifecycle clarity**
   - Document: which config/env vars are startup-only vs hot-reload.
   - Prefer immutable config objects passed to constructors where feasible.

8. **Reduce parallel workflows / legacy surfaces**
   - Remove deprecated flows once the grace period is exceeded.
   - Keep one “golden path” for running locally and in production.

## Inputs
- Generated stats: `artifacts/maintainability/module_stats.md`
- Architectural notes: `docs/architecture/*`, `CORE_PROJECT_ANALYSIS.md`
