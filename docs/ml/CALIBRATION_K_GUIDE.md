# Ensemble K Calibration & Governance Guide

This guide consolidates the logic, flags, and operational practices around the ensemble disagreement scaling factor **k** used by `ensemble_consensus_exporter.py`.

## 1. Concepts

- **Disagreement (`disagreement`)**: Standard deviation of contributing model predictions for the current time bucket.
- **Recommended K (`recommended_k`)**: Raw scaling factor produced by calibration routines (coverage targeting across historical windows).
- **Smoothed K (`k_smooth`)**: Stability-enhanced version of `recommended_k` (e.g., EWMA or window smoothing) to dampen volatility.
- **Applied K (`applied_k`)**: The final factor used to compute `scaled_radius = applied_k * disagreement` (potentially inflated by forecast logic or overridden manually).
- **Conformal Band Radius (`band_radius`)**: External conformal estimate providing a minimum effective radius floor for coverage alignment.
- **Projected / Forecasted Disagreement (`predicted_disagreement`)**: One-step EMA-based forecast of disagreement used for anticipatory widening when enabled.

## 2. Source Selection Hierarchy

Order of precedence for determining `applied_k`:
1. Manual override (from `*_ensemble_k_overrides.json`) if active and not expired.
2. Raw vs smoothed selection:
   - Use `k_smooth` if present (default path) unless raw forced.
   - Use `recommended_k` if `k_smooth` missing or raw forced (CLI or env).
3. Inflation adjustments (if enabled) to ensure future disagreement / conformal band radius is covered.

Resulting `applied_k_source` values:
- `override` (override active)
- `raw` (recommended_k chosen)
- `smooth` (k_smooth chosen)
- `<raw|smooth>+forecast` (inflation applied)
- `override+forecast` (inflation applied atop override)

## 3. Flags & CLI Options

Environment / CLI toggles:

| Flag / Arg | Type | Default | Effect |
|------------|------|---------|--------|
| `G6_USE_RAW_K` | env | unset (false) | Force raw `recommended_k` instead of `k_smooth` when smoothing available. |
| `--use-raw-k` | CLI | false | Same as env; takes effect per invocation. |
| `--inflate-k-from-forecast` | CLI | false | Inflate applied_k so scaled radius anticipates forecasted disagreement and conforms to band radius floor. |
| `--use-forecast-floor` | CLI | false | Treat `applied_k * predicted_disagreement` as an additional floor for coverage hit evaluation. |
| `--override-auto-revert` | CLI | false | Enable automatic override removal once coverage stabilizes. |
| `--override-target-tolerance` | CLI | 0.01 | Absolute tolerance around target coverage considered "stable". |
| `--override-sustain-cycles` | CLI | 2 | Required consecutive stable cycles before auto-revert. |
| `--dry-run-overrides` | CLI | false | Simulate override pruning without persisting file changes. |

## 4. Override Governance

Override file structure: `NIFTY_ensemble_k_overrides.json`
```json
{"overrides": {"1": {"k": 1.45, "expires": 1700012345000}}}
```
- `k`: Manual scaling value applied directly.
- `expires`: Epoch ms after which entry is pruned automatically.
- `stable_cycles`: Added internally to track consecutive cycles meeting stability criteria during auto-revert evaluation.

Auto-revert mechanism (when `--override-auto-revert`):
1. Load calibration sidecar; extract `target` and coverage metrics (`coverage_fast.value`, `coverage_slow.value`).
2. If both coverage values within `override-target-tolerance` of target → increment `stable_cycles`, else reset.
3. When `stable_cycles >= override-sustain-cycles` → write audit line to override log and remove override (unless `--dry-run-overrides`).

## 5. Inflation Logic

Executed only when `--inflate-k-from-forecast` and override not excluded (inflation still permitted even on override—source annotated with `+forecast`):
```
k_need_band     = band_radius / disagreement
k_need_forecast = applied_k * predicted_disagreement / disagreement
applied_k = max(k_before, k_need_band, k_need_forecast)
```
Edge cases:
- If `disagreement <= 0`: inflation falls back to original `k_before`.
- Missing values silently ignored (no inflation).

## 6. Stability & Coverage Metrics

Calibration sidecar fields used:
```json
{
  "recommended_k": 1.25,
  "k_smooth": 1.10,
  "band_radius": 12.3,
  "target": 0.8,
  "coverage_fast": {"value": 0.805},
  "coverage_slow": {"value": 0.798}
}
```
Interpretation:
- `coverage_fast` / `coverage_slow` windows allow dual-timeframe assessment of stabilization.
- Stability requires both within tolerance of `target`.

## 7. Examples (PowerShell)

Force raw k for a single run:
```powershell
$env:G6_USE_RAW_K='1'; python scripts/ml/ensemble_consensus_exporter.py --index NIFTY --horizon 1 --interval 30
```

Use CLI flag instead of env (preferred for clarity):
```powershell
python scripts/ml/ensemble_consensus_exporter.py --index NIFTY --horizon 1 --interval 30 --use-raw-k
```

Enable forecast inflation & auto-revert with stricter stability window:
```powershell
python scripts/ml/ensemble_consensus_exporter.py --index NIFTY --horizon 1 --interval 30 `
  --inflate-k-from-forecast --override-auto-revert `
  --override-target-tolerance 0.005 --override-sustain-cycles 3
```

Dry-run override governance (observe logging, no file mutation):
```powershell
python scripts/ml/ensemble_consensus_exporter.py --index NIFTY --horizon 1 --interval 30 --override-auto-revert --dry-run-overrides
```

## 8. Monitoring & Auditing

Generated artifacts:
- Ensemble CSV: `NIFTY_ensemble.csv` (columns: `applied_k`, `applied_k_source`, `scaled_radius`, etc.)
- Calibration: `NIFTY_ensemble_k_calibration.json`
- Overrides: `NIFTY_ensemble_k_overrides.json`
- Quarantine log: `NIFTY_ensemble_quarantine.log`
- Override audit log: `NIFTY_ensemble_k_overrides.log`

Recommended periodic checks:
| Check | Purpose |
|-------|---------|
| `applied_k_source` distribution | Detect persistent override or excessive forecast reliance. |
| Override audit log entries | Ensure auto-revert triggers appropriately. |
| Coverage metrics vs target | Validate calibration quality, avoid chronic under/over widening. |

## 9. Common Scenarios

| Scenario | Expected Source | Notes |
|----------|-----------------|-------|
| Stable regime, smoothing available | `smooth` | Typical daily operation. |
| Early calibration window (no smoothing yet) | `raw` | Smoothing absent → fallback raw. |
| Manual widening due to volatility | `override` | Operator-chosen K. |
| Override plus forecast inflation | `override+forecast` | Anticipatory widening layered. |
| Raw forced via env + forecast inflation | `raw+forecast` | Test/AB path. |
| Override expired or auto-reverted | `smooth` | Governance restored. |

## 10. Troubleshooting

- `applied_k_source` stuck on `override`: Verify expiry or stability conditions; consider lowering `--override-sustain-cycles` or raising `override-target-tolerance` slightly.
- Inflation not triggering: Confirm `--inflate-k-from-forecast` set and `band_radius > disagreement * applied_k` or `predicted_disagreement > disagreement`.
- Excessive band widening: Inspect `recommended_k` vs `k_smooth`; smoothing parameters may need recalibration.
- Override removal not happening: Ensure calibration sidecar includes `coverage_fast` and `coverage_slow` value fields.

## 11. Test Coverage Summary

Implemented tests:
- `test_ensemble_applied_k.py`: raw vs smooth selection, override precedence.
- `test_ensemble_k_precedence.py`: env/CLI forcing, missing smoothing, expired override.
- `test_ensemble_k_forecast_inflation.py`: inflation via band radius.
- `test_ensemble_k_override_auto_revert.py`: stability-based auto-revert.

Planned extensions:
- Forecast-driven inflation where `predicted_disagreement > disagreement`.
- Multi-horizon override governance tests.

---
Maintainers: Update this guide upon changes to calibration schema or governance rules.
