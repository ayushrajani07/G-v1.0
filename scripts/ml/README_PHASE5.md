# Phase 5: Evaluation & Continuous Improvement Scripts

Quick reference guide for Phase 5 evaluation scripts.

## Available Scripts

### 1. A/B Testing (`ab_test_ensemble.py`)

Compare performance between model variants.

**Quick Start:**
```bash
python ab_test_ensemble.py \
    --index NIFTY \
    --variant-a ensemble \
    --variant-b retrieval_only \
    --duration-days 7
```

**Key Options:**
- `--index`: Index to test (NIFTY, BANKNIFTY)
- `--variant-a/b`: Names of variants to compare
- `--duration-days`: Test period duration
- `--data-path`: Path to test data CSV
- `--output`: Output path for report

---

### 2. Regime Evaluation (`evaluate_by_regime.py`)

Analyze performance across market regimes.

**Quick Start:**
```bash
python evaluate_by_regime.py \
    --index NIFTY \
    --days 30 \
    --regimes high_vol,low_vol,trending,sideways
```

**Regimes:**
- `high_vol`: IV > 80th percentile
- `low_vol`: IV < 20th percentile
- `trending`: |Price change| > 1%/hour
- `sideways`: |Price change| < 0.3%/hour

**Key Options:**
- `--index`: Index to evaluate
- `--days`: Number of days to analyze
- `--regimes`: Comma-separated regime list
- `--data-path`: Path to evaluation data
- `--output`: Output path for report

---

### 3. Feature Importance Tracking (`track_feature_importance.py`)

Monitor feature importance stability.

**Quick Start:**
```bash
python track_feature_importance.py \
    --model models/nifty_gbrt_quantile/ \
    --output reports/feature_importance.html
```

**Key Options:**
- `--model`: Path to trained model directory
- `--output`: Output HTML report path
- `--history`: Path to history JSON (for tracking)
- `--quantile`: Quantile model to analyze (0.5 = median)
- `--top-k`: Number of top features (default: 15)

**Stability Criteria:**
- CV < 0.5 (Coefficient of Variation)
- Appearance rate > 75%

---

### 4. Model Drift Detection (`detect_model_drift.py`)

Detect performance degradation and feature drift.

**Quick Start:**
```bash
python detect_model_drift.py \
    --index NIFTY \
    --baseline-period 30d \
    --test-period 7d \
    --alert-threshold 0.15
```

**Key Options:**
- `--index`: Index to check
- `--baseline-period`: Reference period (e.g., 30d, 4w)
- `--test-period`: Recent period to compare (e.g., 7d, 1w)
- `--alert-threshold`: MAE degradation threshold (0.15 = 15%)
- `--check-features`: Also check feature distribution drift
- `--data-path`: Path to evaluation data
- `--output`: Output path for report

**Exit Codes:**
- `0`: No drift
- `1`: Drift detected
- `2`: Error

---

## Common Workflows

### Weekly Evaluation

```bash
#!/bin/bash
INDEX="NIFTY"
DATE=$(date +%Y%m%d)

# Feature importance
python track_feature_importance.py \
    --model models/${INDEX}_gbrt_quantile/ \
    --output reports/feature_importance_${DATE}.html

# Regime analysis
python evaluate_by_regime.py \
    --index ${INDEX} \
    --days 30 \
    --output reports/regime_eval_${DATE}.json

# Drift check
python detect_model_drift.py \
    --index ${INDEX} \
    --baseline-period 30d \
    --test-period 7d \
    --output reports/drift_${DATE}.json \
    --check-features

if [ $? -eq 1 ]; then
    echo "ALERT: Drift detected!"
fi
```

### A/B Test New Version

```bash
python ab_test_ensemble.py \
    --index NIFTY \
    --variant-a ensemble_v2 \
    --variant-b ensemble_v1 \
    --duration-days 7 \
    --output reports/ab_test_v2.json
```

---

## Data Format Requirements

### Evaluation Data CSV

Required columns:
- `timestamp`: ISO datetime
- `tp_actual`: Actual TP values
- `pred_p50`: P50 predictions
- `pred_p10`: P10 predictions (for coverage)
- `pred_p90`: P90 predictions (for coverage)
- `avg_iv`: Average implied volatility (for regime)
- `index_price`: Index price (for regime)
- `baseline_tp`: Baseline TP (optional)

Optional feature columns (for drift detection):
- `residual_lag_*`
- `residual_roll_mean_*`
- `residual_roll_std_*`
- `index_return_*`
- `iv_*`
- `minutes_to_expiry`
- `time_*`

---

## Output Formats

### JSON Reports

All scripts output JSON reports with:
- Metadata (timestamp, configuration)
- Metrics (performance numbers)
- Analysis (comparisons, statistics)
- Summary (recommendations)

### HTML Reports

Feature importance tracker generates HTML with:
- Current feature rankings
- Visual importance bars
- Stability analysis table
- Historical summary

---

## Troubleshooting

### "Data file not found"

**Solution:** Provide `--data-path` pointing to evaluation CSV

```bash
python evaluate_by_regime.py \
    --data-path data/ml/evaluation/nifty_eval.csv
```

### "No valid samples"

**Causes:**
- Missing required columns
- All values are NaN
- Insufficient data

**Solution:** Check data quality and column names

### "Insufficient history for stability"

**Solution:** Run feature importance tracker multiple times (min 4 records)

---

## Performance Tips

1. **Use appropriate periods:**
   - Baseline: 30-60 days
   - Test: 7-14 days
   - A/B test: minimum 7 days

2. **Adjust thresholds based on use case:**
   - Conservative: 0.20 (fewer alerts)
   - Standard: 0.15 (recommended)
   - Aggressive: 0.10 (early detection)

3. **Check data quality first:**
   ```bash
   python -c "import pandas as pd; df = pd.read_csv('data.csv'); print(df.info())"
   ```

---

## Testing

Run tests for all Phase 5 components:

```bash
pytest tests/ml/test_ab_testing.py tests/ml/test_regime_evaluation.py -v
```

Expected: 15/15 tests passing

---

## Documentation

- Full guide: `docs/ml/PHASE5_EVALUATION_GUIDE.md`
- Implementation roadmap: `docs/ml/ML_ARM_IMPLEMENTATION_ROADMAP.md`
- Test files: `tests/ml/test_ab_testing.py`, `tests/ml/test_regime_evaluation.py`

---

## Support

For issues or questions:
1. Check documentation in `docs/ml/`
2. Review test cases for usage examples
3. Check script help: `python <script>.py --help`
