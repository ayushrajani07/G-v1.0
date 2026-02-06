# Providers & Brokerage

## Scope
External API access, token/auth, provider adapters, retries/backoff, provider selection.

## Primary code
- `src/broker/` (notably high exception density)
- `src/providers/`, `src/provider/`
- Token tooling in `src/tools/`

## Signals (from generated stats)
- `src/broker`: ~5.4k LOC; **~196** `except Exception` occurrences.
- `src/providers` + `src/provider`: smaller modules but still present catch-all usage.

## Hotspot files (good first refactor targets)
- `src/broker/kite_provider.py`
- `src/broker/kite/options.py`
- `src/broker/kite/quotes.py`

## Current architecture (observed)

There are *three parallel “provider abstraction” tracks* today:

1. **Legacy / production provider implementation**
	- `src/broker/kite_provider.py` is the main provider facade; it delegates to extracted helpers under `src/broker/kite/*`.

2. **New provider skeleton**
	- `src/provider/*` (e.g., `ProviderConfig`, `AuthManager`, `ProviderCore`, `provider/errors.py` taxonomy).
	- `src/provider/facade.py` currently *delegates back to the legacy provider* (migration shim).

3. **Provider selection utilities**
	- `src/broker/provider_registry.py` (register/get provider by `G6_PROVIDER`).
	- `src/providers/factory.py` (creates providers, tries registry first for `auto`, else falls back to kite provider).
	- `src/providers/composite_provider.py` (failover wrapper, currently catches all exceptions).
	- `src/collectors/providers_interface.py` (`Providers` wrapper that adds enrichment + fallbacks; also catches all exceptions).

Net result: it’s easy to accidentally introduce new “entry points” that drift in behavior.

## Maintainability risks
- **Namespace split (`broker` vs `provider` vs `providers`)** creates duplicate abstraction layers and unclear ownership.
- **Multiple factories/registries** (`provider_registry`, `create_provider`, `provider.facade`, `Providers` wrapper) makes provider selection hard to reason about.
- **Exception swallowing as control flow**:
  - `src/broker/kite/quotes.py` uses broad `except Exception` + synthetic fallback, which can mask real contract breaks.
  - `src/providers/composite_provider.py` catches `Exception` and continues failover even for “fatal” bugs.
  - `src/collectors/providers_interface.py` catches exceptions and injects synthetic prices; this pushes provider policy *up into collectors*.
- **Inconsistent error taxonomy usage**:
  - Some paths classify into `src/provider/errors.py`.
  - Others route through legacy `src/error_handling.handle_provider_error`.
- **Metrics/API mismatch risk**: `CompositeProvider` references labeled failover metrics, while the generated `g6_provider_failover_total` metric is defined without labels (easy to drift / silently fail).

## Improvements

### 1) Pick a single canonical abstraction surface

Target end state:
- **Canonical implementation namespace**: `src/provider/*` owns provider contracts, config, error taxonomy, and selection.
- `src/broker/*` becomes an *implementation detail* (e.g., “kite implementation”), or is renamed/migrated under `src/provider/impl/kite/*`.
- `src/providers/*` becomes compatibility shims only (or is removed after deprecation window).

Concrete action:
- Define a single `ProviderProtocol` (or ABC) with the minimum required methods used by collectors:
  - `get_instruments`, `get_quote`, `get_ltp`, `resolve_expiry`, `get_expiry_dates` (and any required diagnostics hooks).

### 2) Standardize provider selection (one factory + one registry)

Concrete action:
- Make **one** canonical entrypoint for “build provider”: e.g. `src/provider/factory.py` (new) that:
  - reads `G6_PROVIDER` (or explicit arg)
  - uses `provider_registry.get_provider(...)`
  - optionally wraps with `CompositeProvider` if configured
- Deprecate direct use of:
  - `src/providers/factory.create_provider`
  - `src/provider/facade._legacy_provider()` for production callsites (keep for tests/migration only)

### 3) Make error handling typed and policy-driven (reduce blanket `except Exception`)

Concrete action:
- Treat `src/provider/errors.py` as the **only** provider error taxonomy.
- In failover wrappers (`CompositeProvider`) and in collectors, handle by category:
  - `ProviderAuthError` → attempt refresh path or fail fast (don’t silently failover forever)
  - `ProviderTimeoutError` / `ProviderRecoverableError` → retry/backoff then failover
  - `ProviderFatalError` → fail-cycle (bug/contract change), do **not** failover

Practical “first cut” change (low risk):
- Replace `except Exception: continue` patterns with `except ProviderRecoverableError: continue` and let fatal errors bubble.

### 4) Move “synthetic fallback” policy to the provider layer

Concrete action:
- Decide where synthetic values are allowed:
  - inside the provider (recommended) so callers always see consistent shapes
  - or in a dedicated “FallbackProvider” wrapper that is explicitly composed
- Reduce synthetic injection from `src/collectors/providers_interface.py` (today it injects index prices and OHLC).

Current implementation note:
- Provider helpers now support a strict mode via `G6_PROVIDER_SYNTHETIC_FALLBACK=0` (surface real failures by raising typed `Provider*Error` instead of returning fabricated defaults).

### 5) Tighten observability contracts

Concrete action:
- Ensure provider failover metrics and events use a consistent schema:
  - either add labels to failover metric (if desired), or remove `.labels(...)` usage.
  - make event emission best-effort but structured.

## Suggested sequencing (realistic refactor plan)

1. **Document and freeze the canonical provider selection path**
	- One “how we choose providers” doc section (env + defaults + failover).
2. **Introduce `ProviderProtocol` + typed errors at module boundaries**
	- Add protocol in `src/provider/` or `src/types/`.
3. **Fix failover semantics**
	- `CompositeProvider` should only fail over on recoverable errors.
4. **Deprecate `Providers` wrapper**
	- Move enrichment/instrument mapping responsibilities into provider or a dedicated adapter.
5. **Shrink `kite_provider.py` optional-import surface**
	- Replace internal-module `try/except ImportError` patterns with stable imports once cyclic deps are resolved.

## “First PR” candidates (high ROI, low blast radius)

1. **Failover correctness PR**
	- Update `src/providers/composite_provider.py` to only fail over on `ProviderRecoverableError`/`ProviderTimeoutError`, and to fail fast on `ProviderFatalError`.
	- Align failover metric usage with the generated metric definition.

2. **Typed provider error propagation PR**
	- In `src/broker/kite/quotes.py`, reduce broad catch/return-synthetic blocks; at minimum, wrap unexpected exceptions into `ProviderFatalError` and let them propagate when synthetic fallback is disabled.

3. **Duplicate mapping cleanup PR**
	- Replace the hard-coded index→instrument mapping in `src/collectors/providers_interface.py` with a shared canonical mapping (currently exists in `src/broker/kite_provider.py`).
