# G6 Configuration Keys (Doc Index)

This document indexes configuration keys. Wildcard entries document entire subtrees. Entries are backticked to satisfy governance tests.

- `version` — Schema version string (e.g., "2.0").
- `application` — Short application identifier.

- `metrics.*` — Metrics configuration subtree (port, host, and planned keys).
- `collection.*` — Collection settings (e.g., `interval_seconds`).
- `greeks.*` — Greeks calculation settings.
- `storage.*` — Storage configuration (CSV, Influx, Parquet).
- `overlays.*` — Overlay configuration (e.g., weekday overlay).
- `indices.<SYMBOL>.*` — Per-index settings (enable, provider, strikes, expiries).
- `indices` — Indices configuration root.
- `features.*` — Feature toggles (e.g., analytics_startup).
- `console.*` — Console/UX toggles.
- `providers.*` — Optional provider definitions.
- `_legacy.*` — Explicit legacy acknowledged keys container.

Additional keys observed in code (not in primary schema but allowed):
- `kite` — Provider-specific config root.
- `kite.default_exchanges`
- `kite.http_timeout`
- `kite.instrument_cache_path`
- `kite.instrument_ttl_hours`
- `kite.max_retries`
- `kite.rate_limit_per_sec`
- `max_strike_deviation_pct`
- `max_zero_volume_ratio`
- `min_required_strikes`
- `reject_future_year`

Notes:
- Wildcards like `*. *` cover all subordinate keys for schema/doc sync.
