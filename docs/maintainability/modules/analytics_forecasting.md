# Analytics & Forecasting

## Scope
Option analytics (IV/Greeks/PCR), path forecasting, ANN/ML utilities, adaptive gating heuristics.

## Primary code
- `src/analytics/`
- `src/path_forecast/`
- `src/ml/`
- `src/adaptive/`

## Signals (from generated stats)
- `src/analytics`: ~2.6k LOC; ~79 `except Exception` occurrences.
- `src/path_forecast`: ~2.2k LOC; ~47 `except Exception` occurrences.
- `src/adaptive`: ~1.8k LOC; ~73 `except Exception` occurrences.

## Maintainability risks
- Numeric code can hide edge cases behind broad exception handling.
- Mixed concerns: analytics computation vs data-quality/validation vs persistence formatting.

## Improvements
- Make analytic functions pure where possible (inputs in, outputs out).
- Define explicit validation/normalization at module boundaries.
- Add golden test vectors (deterministic fixtures) for key computations.
