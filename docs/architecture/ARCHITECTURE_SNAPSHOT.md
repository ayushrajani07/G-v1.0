# Architecture Snapshot

A quick, high-level orientation to the major layers.

| Layer | Path(s) | Responsibilities |
|-------|---------|------------------|
| Entry / Orchestration | `src/unified_main.py` | Bootstrap, feature toggles, graceful loop |
| Collectors | `src/collectors/unified_collectors.py` | Per-cycle orchestration, optional snapshot build |
| Providers Facade | `src/collectors/providers_interface.py`, `src/broker/kite_provider.py` | Expiry & instrument resolution, quotes |
| Analytics | `src/analytics/option_greeks.py`, `src/analytics/option_chain.py` | IV estimation, Greeks, PCR, breadth |
| Storage | `src/storage/csv_sink.py`, `src/storage/influx_sink.py` | Persistent per-option & overview writes |
| Metrics | `src/metrics/metrics.py` | Registration, grouped gating, metadata dump |
| Panels & Summary | `scripts/summary/app.py`, `src/panels/*` | Real-time textual panels & JSON artifact emission |
| Panel Integrity | `src/panels/validate.py` | Manifest hash verification & schema validation |
| Health & Resilience | `src/health/*`, `src/utils/*` | Circuit breakers, retries, memory pressure, symbol hygiene |
| Token / Auth | `src/tools/token_manager.py`, `src/tools/token_providers/*` | Provider token acquisition |
| Config & Docs Governance | `src/config/*`, tests in `tests/` | Schema validation, doc coverage enforcement |
