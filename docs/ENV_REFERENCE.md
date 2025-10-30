# Environment Tuning Reference

Generated: 2025-10-28
Audience: Operators and on-call engineers. This is a curated, human-friendly guide to the most impactful runtime environment variables for stability and latency. It complements (not replaces) the auto catalogs: `docs/ENV_VARS_CATALOG.md` and `docs/ENV_VARS_AUTO.md`.

## Quick-start profiles

- Conservative (safest under tight provider limits)
  - G6_KITE_LIMITER=1, G6_KITE_QPS=2, G6_KITE_RATE_MAX_BURST=4
  - G6_KITE_QUOTE_BATCH=1, G6_KITE_QUOTE_BATCH_WINDOW_MS=25, G6_KITE_QUOTE_CACHE_SECONDS=2.0
  - G6_PARALLEL_INDEX_WORKERS=1, G6_KITE_TIMEOUT_SEC=5, G6_KITE_INSTRUMENTS_TIMEOUT_SEC=10
  - G6_QUOTE_SKIP_LTP_ON_RATELIMIT=1
- Standard (balanced; default recommendation)
  - G6_KITE_LIMITER=1, G6_KITE_QPS=3, G6_KITE_RATE_MAX_BURST=6
  - G6_KITE_QUOTE_BATCH=1, G6_KITE_QUOTE_BATCH_WINDOW_MS=20, G6_KITE_QUOTE_CACHE_SECONDS=2.0
  - G6_PARALLEL_INDEX_WORKERS=2, G6_KITE_TIMEOUT_SEC=5, G6_KITE_INSTRUMENTS_TIMEOUT_SEC=10
  - G6_QUOTE_SKIP_LTP_ON_RATELIMIT=1
- Aggressive (when limits are generous and errors are rare)
  - G6_KITE_LIMITER=1, G6_KITE_QPS=5, G6_KITE_RATE_MAX_BURST=10
  - G6_KITE_QUOTE_BATCH=1, G6_KITE_QUOTE_BATCH_WINDOW_MS=15, G6_KITE_QUOTE_CACHE_SECONDS=1.0
  - G6_PARALLEL_INDEX_WORKERS=4, G6_KITE_TIMEOUT_SEC=4, G6_KITE_INSTRUMENTS_TIMEOUT_SEC=8
  - G6_QUOTE_SKIP_LTP_ON_RATELIMIT=1

## Provider rate limiting and pacing

- G6_KITE_LIMITER (bool; default: off)
  - Enable the client-side token-bucket limiter for Kite API calls.
- G6_KITE_QPS (int; default: 3)
  - Sustained allowed requests per second.
- G6_KITE_RATE_MAX_BURST (int; default: 2×QPS)
  - Bucket capacity for short bursts before throttling.
- G6_KITE_TIMEOUT_SEC (float; default: 0 = provider default)
  - Per-request timeout seconds for Kite calls.
- G6_KITE_INSTRUMENTS_TIMEOUT_SEC (float; default: unset)
  - Higher timeout specifically for instrument metadata fetches.

## Quote batching and caching

- G6_KITE_QUOTE_BATCH (bool; default: off)
  - Coalesce near-simultaneous quote requests into one provider call.
- G6_KITE_QUOTE_BATCH_WINDOW_MS (int; default: 15)
  - Window in ms to aggregate requests when batching is enabled.
- G6_KITE_QUOTE_CACHE_SECONDS (float; default: 1.0)
  - In‑memory per-symbol TTL cache; fresh hits bypass the provider.
- G6_QUOTE_SKIP_LTP_ON_RATELIMIT (bool; default: on)
  - When a quote call is rate-limited, skip an immediate LTP fallback call to avoid compounding 429s and synthesize from available data instead.

## Parallelism and cycle control

- G6_PARALLEL_INDEX_WORKERS (int; default: 4)
  - Max concurrent per-index workers; reduce to soften pressure on providers.
- G6_PARALLEL_INDEX_TIMEOUT_SEC (float; default: 0.25×interval)
  - Soft per-index timeout in parallel mode before retry/skip.
- G6_LOOP_INTERVAL_SECONDS (float; default: config)
  - Orchestrator loop cadence override; higher values reduce load.

## Observability and logging helpers

- G6_JSON_LOGS (bool; default: off)
  - Emit structured JSON logs for easier ingestion and filtering.
- G6_FANCY_CONSOLE (auto|always|never; default: auto)
  - Tweak terminal rendering; set `never` for ultra-lean consoles.

## CSV/panels sinks (optional pressure valves)

- G6_DISABLE_PER_OPTION_METRICS (bool; default: off)
  - Reduce metrics cardinality when troubleshooting.
- G6_PANELS_INCLUDE (csv; default: all)
  - Restrict emitted panels to a subset for focused debugging.

## Tuning guidance

- Start with the Standard profile. If 429/Too Many Requests persists, step down QPS and/or raise batching window.
- Prefer increasing cache TTL before increasing QPS.
- Keep timeouts modest (4–6s) to avoid thread starvation during provider slowdowns.
- Lower parallel workers when you see bursts of rate-limit errors.

## How to apply

- Edit `.env` in the project root and set the variables. Example:
  - G6_KITE_LIMITER=1
  - G6_KITE_QPS=3
  - G6_KITE_RATE_MAX_BURST=6
  - G6_KITE_QUOTE_BATCH=1
  - G6_KITE_QUOTE_BATCH_WINDOW_MS=20
  - G6_KITE_QUOTE_CACHE_SECONDS=2.0
  - G6_KITE_TIMEOUT_SEC=5.0
  - G6_KITE_INSTRUMENTS_TIMEOUT_SEC=10.0
  - G6_PARALLEL_INDEX_WORKERS=2
  - G6_QUOTE_SKIP_LTP_ON_RATELIMIT=1

See also:
- docs/ENV_VARS_CATALOG.md — comprehensive, auto-generated catalog (source: docs/env_dict.md)
- docs/ENV_VARS_AUTO.md — auto inventory and coverage summary
