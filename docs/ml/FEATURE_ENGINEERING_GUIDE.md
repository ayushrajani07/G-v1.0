# Feature Engineering Guide

**Status:** Active  
**Phase:** Phase 1 - Feature Engineering and Data Preparation  
**Last Updated:** 2025-11-16

---

## Overview

This guide documents the feature engineering pipeline for ML-based TP (Total Premium) forecasting. The pipeline extracts 24 features from historical data to train quantile GBRT models for residual forecasting.

## Feature Engineering Pipeline

### Architecture

```
Raw Data (TP, Index Price, IV, Time) 
    ↓
Baseline TP Computation (Structural Formula)
    ↓
Residual Calculation (actual - baseline)
    ↓
Feature Extraction (24 features)
    ↓
Feature Validation
    ↓
Training-Ready Dataset
```

## Feature Groups

### 1. Lag Features (12 features)

**Purpose:** Capture recent residual history and temporal patterns.

#### Residual Lags (6 features)
- `residual_lag_1`: Residual from 1 minute ago
- `residual_lag_2`: Residual from 2 minutes ago
- `residual_lag_5`: Residual from 5 minutes ago
- `residual_lag_10`: Residual from 10 minutes ago
- `residual_lag_30`: Residual from 30 minutes ago
- `residual_lag_60`: Residual from 60 minutes ago

**Rationale:** Recent residuals are strong predictors of near-term residuals due to market momentum and mean reversion patterns.

#### Rolling Mean (3 features)
- `residual_rolling_mean_5`: 5-minute rolling mean of residuals
- `residual_rolling_mean_15`: 15-minute rolling mean of residuals
- `residual_rolling_mean_30`: 30-minute rolling mean of residuals

**Rationale:** Smoothed residual trends capture sustained deviations from baseline.

#### Rolling Std (3 features)
- `residual_rolling_std_5`: 5-minute rolling std of residuals
- `residual_rolling_std_15`: 15-minute rolling std of residuals
- `residual_rolling_std_30`: 30-minute rolling std of residuals

**Rationale:** Residual volatility indicates forecast uncertainty and regime shifts.

### 2. Market Features (8 features)

**Purpose:** Capture market dynamics affecting TP.

#### Price Returns (2 features)
- `index_return_1m`: 1-minute index price return
- `index_return_5m`: 5-minute index price return

**Rationale:** Price momentum affects option demand and premiums.

#### Volatility Metrics (2 features)
- `avg_iv`: Current average implied volatility level
- `iv_change_1m`: 1-minute change in IV

**Rationale:** IV is a primary driver of option prices. Changes in IV signal market uncertainty.

#### Time Features (4 features)
- `minutes_to_expiry_norm`: Normalized time to expiry (0-1 scale)
- `time_of_day_sin`: Sine encoding of time (9:15 AM - 3:30 PM)
- `time_of_day_cos`: Cosine encoding of time
- `weekday`: Day of week (0=Monday, 6=Sunday)

**Rationale:** Time to expiry affects theta decay. Intraday patterns (e.g., opening volatility) and day-of-week effects are common in options markets.

### 3. Regime Features (4 features)

**Purpose:** Identify market regimes for context-aware forecasting.

#### Volatility Regime (2 features)
- `iv_percentile`: IV percentile over 60-minute rolling window
- `index_vol_percentile`: Realized volatility percentile

**Rationale:** High vs. low volatility regimes have different forecast characteristics.

#### Trading Activity (2 features)
- `volume_ratio`: Current volume / daily average volume **(placeholder)**
- `oi_change_rate`: Open interest change rate **(placeholder)**

**Rationale:** Volume and OI changes indicate liquidity and market participation. Currently placeholders pending data availability.

**Note:** Volume and OI features are placeholders (constant values) in synthetic data. In production, these should be computed from real market data.

---

## Usage

### 1. Feature Extraction

```python
from src.analytics.ml.feature_engineering import FeatureEngineer

# Initialize
fe = FeatureEngineer()

# Extract features from DataFrame
df_with_features = fe.extract_features(
    df,
    tp_col="tp_actual",
    tp_baseline_col="tp_baseline",
    index_price_col="underlying",
    iv_col="avg_iv",
    minutes_to_expiry_col="minutes_to_expiry",
    timestamp_col="timestamp"
)

# Get feature names
feature_names = fe.get_feature_names()  # Returns list of 24 features

# Validate features
is_valid, issues = fe.validate_features(df_with_features)
if not is_valid:
    for issue in issues:
        print(f"Issue: {issue}")

# Get statistics
stats = fe.get_feature_statistics(df_with_features)
```

### 2. Dataset Generation

Generate training datasets using the command-line script:

```bash
# Generate NIFTY dataset
python scripts/ml/generate_training_dataset.py \
    --index NIFTY \
    --days 60 \
    --output data/ml/training/nifty_tp_features_60d.csv \
    --compute-baseline \
    --validate

# Generate BANKNIFTY dataset
python scripts/ml/generate_training_dataset.py \
    --index BANKNIFTY \
    --days 60 \
    --output data/ml/training/banknifty_tp_features_60d.csv \
    --compute-baseline \
    --validate \
    --k-coefficient 1.0

# Use custom input data
python scripts/ml/generate_training_dataset.py \
    --input data/historical/nifty_options.csv \
    --output data/ml/training/nifty_custom.csv \
    --compute-baseline \
    --validate
```

### 3. Dataset Validation

Validate generated datasets:

```bash
python scripts/ml/validate_features.py \
    --dataset data/ml/training/nifty_tp_features_60d.csv \
    --min-completeness 0.9 \
    --min-correlation 0.85 \
    --verbose
```

---

## Data Quality Checks

The feature engineering pipeline includes comprehensive validation:

### 1. Feature Presence
- All 24 features must be present
- Required columns: `tp_actual`, `tp_baseline`, `tp_residual`

### 2. Data Completeness
- No NaN values in features (after lag period)
- No infinite values
- Minimum 90% completeness for each feature

### 3. Baseline Quality
- Baseline correlation with actual TP ≥ 0.85
- Residual mean close to zero (well-calibrated)
- Residual std reasonable

### 4. Feature Distributions
- No constant features (except placeholders)
- Reasonable value ranges
- No extreme outliers

---

## Feature Importance (Expected)

Based on domain knowledge, expected feature importance ranking:

**High Importance:**
1. `residual_lag_1`, `residual_lag_2` - Recent residuals
2. `avg_iv`, `iv_change_1m` - Volatility metrics
3. `minutes_to_expiry_norm` - Time to expiry
4. `residual_rolling_mean_5` - Short-term trend

**Medium Importance:**
5. `index_return_1m`, `index_return_5m` - Price momentum
6. `iv_percentile` - Volatility regime
7. `residual_lag_5`, `residual_lag_10` - Medium lags
8. `residual_rolling_std_5` - Short-term volatility

**Lower Importance:**
9. Time encoding features - Intraday patterns
10. Longer lags - Less predictive
11. Volume/OI features - Pending real data

Actual importance will be determined during model training (Phase 2).

---

## Configuration

### FeatureEngineer Parameters

```python
fe = FeatureEngineer(
    lag_periods=[1, 2, 5, 10, 30, 60],  # Lag windows in minutes
    rolling_windows=[5, 15, 30],         # Rolling stat windows
    price_return_windows=[1, 5],         # Price return windows
    min_minutes_to_expiry=1.0,           # Min time bound
    max_minutes_to_expiry=375.0,         # Max time bound (full day)
)
```

### Baseline Parameters

```python
# Baseline formula: baseline_tp = k * underlying * iv * sqrt(T)
k = 1.0  # Scaling coefficient (tune if needed)
```

---

## Output Files

### Generated Dataset
**File:** `data/ml/training/nifty_tp_features_60d.csv`

**Columns:**
- Input columns: `timestamp`, `index`, `underlying`, `ce_iv`, `pe_iv`, `avg_iv`, `tp_actual`, `minutes_to_expiry`
- Computed: `tp_baseline`, `tp_residual`
- Features: 24 feature columns

### Statistics
**File:** `data/ml/training/nifty_tp_features_60d_stats.json`

Contains:
- Total samples
- Feature count
- Feature names
- Per-feature statistics (mean, std, min, max, quartiles, NaN counts)

### Validation Report
**File:** `data/ml/training/nifty_tp_features_60d_validation.txt`

Contains:
- Total samples
- Feature count
- Validation status (pass/fail)
- Baseline correlation
- List of issues (if any)

---

## Best Practices

### 1. Data Requirements
- **Minimum:** 30 days of historical data
- **Recommended:** 60 days for robust training
- **Granularity:** 1-minute level
- **Completeness:** >90% of trading minutes

### 2. Baseline Calibration
- Start with k=1.0
- If baseline correlation < 0.85, tune k coefficient
- Ensure residual mean close to zero

### 3. Feature Engineering
- Keep lag periods reasonable (1-60 minutes)
- Use rolling windows that match market dynamics
- Update volume/OI placeholders when data available

### 4. Validation
- Always validate after generation
- Check for data leakage (future info in features)
- Verify temporal ordering

---

## Troubleshooting

### Low Baseline Correlation (<0.85)

**Symptoms:** `baseline_correlation < 0.85` in validation

**Solutions:**
1. Tune k coefficient: Try k ∈ [0.8, 1.2]
2. Check IV quality: Ensure average of CE/PE IVs is reasonable
3. Check time to expiry: Verify minutes_to_expiry is accurate
4. Review underlying prices: Ensure no data errors

### High NaN Counts

**Symptoms:** Features have >10% NaN values

**Solutions:**
1. Check data completeness: Fill gaps in input data
2. Review lag periods: First 60 samples will have NaN in lag_60
3. Consider imputation: Forward-fill or interpolate if appropriate

### Constant Features

**Symptoms:** Feature std ≈ 0

**Solutions:**
1. Check if placeholder: volume_ratio, oi_change_rate are expected to be constant
2. Review data source: Real data should have variation
3. Verify computation: Ensure feature extraction logic is correct

### Memory Issues

**Symptoms:** Out of memory during dataset generation

**Solutions:**
1. Process in batches: Split into smaller time periods
2. Use chunking: Read CSV in chunks
3. Reduce precision: Use float32 instead of float64
4. Sample data: Use subset for initial testing

---

## References

1. `ML_ARM_IMPLEMENTATION_ROADMAP.md` - Phase 1 specifications
2. `src/analytics/ml/feature_engineering.py` - Implementation
3. `scripts/ml/generate_training_dataset.py` - Dataset generation
4. `tests/ml/test_feature_engineering.py` - Unit tests

---

## Change Log

### 2025-11-16 - Initial Release
- Feature engineering module implemented
- 24 features (12 lag, 8 market, 4 regime)
- Dataset generation script
- Validation script
- Comprehensive test coverage

---

**Next Steps:** Phase 2 - GBRT Model Training

Use the generated datasets to train quantile GBRT models. See `docs/ml/MODEL_TRAINING_GUIDE.md` (coming soon).
