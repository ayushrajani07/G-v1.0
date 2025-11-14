# Collector Settings Unification (Phase 3)

Date: 2025-11-11

Summary:
- Canonical settings module is `src/collectors/settings.py`.
- Use `from src.collectors.settings import get_collector_settings, CollectorSettings`.
- The legacy shim `src/collector/settings.py` remains for compatibility and emits a DeprecationWarning.

Notes:
- `get_collector_settings(force_reload=False)` returns a process-singleton settings object.
- Tests may call `get_collector_settings(force_reload=True)` to re-hydrate after env mutations.
- Avoid importing the deprecated `src.collector.settings`; search and replace to canonical path when touching files.
