# Configuration & Governance

## Scope
Config loading/validation, env var policy, schema docs, governance tests.

## Primary code
- `src/config/`
- `src/schema/`
- tests under `tests/config/` and related governance suites

## Signals (from generated stats)
- `src/config`: ~2.4k LOC; ~31 `except Exception` occurrences.

## Maintainability risks
- Confusion between startup-only vs hot-reload behavior.
- Multiple config access patterns in production code.

## Improvements
- Define a clear config lifecycle policy and enforce it:
  - immutable config object passed down
  - runtime flags explicitly separated (and documented)
- Provide one canonical config facade and deprecate alternates.
- Keep schema/doc generation as a first-class governance test.
