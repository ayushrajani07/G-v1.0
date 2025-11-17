# ML Module Documentation

**Machine Learning for TP Forecasting**

This directory contains documentation for the ML-based Total Premium (TP) forecasting system.

---

## Quick Links

### 📋 Current Status & Planning
- **[ML ARM Next Steps](ML_ARM_NEXT_STEPS.md)** - ⭐ **POST-IMPLEMENTATION GUIDANCE** - What to do after roadmap completion
- **[ML ARM Implementation Roadmap](ML_ARM_IMPLEMENTATION_ROADMAP.md)** - All phases complete (7/7) - 100%

### 📚 Implementation Guides
- **[Feature Engineering Guide](FEATURE_ENGINEERING_GUIDE.md)** - Complete guide to Phase 1 feature extraction
- **[Phase 1 Completion Summary](PHASE1_COMPLETION_SUMMARY.md)** - Implementation details and results
- **[Ensemble Guide](ENSEMBLE_GUIDE.md)** - Phase 3 ensemble forecaster guide
- **[Production Deployment Guide](PRODUCTION_DEPLOYMENT_GUIDE.md)** - Phase 4 deployment instructions

---

## Implementation Status

### 🎉 ALL PHASES COMPLETE (7/7 - 100%)

**Completion Date:** 2025-11-17  
**Status:** Production Ready

| Phase | Status | Deliverables | Tests |
|-------|--------|--------------|-------|
| **Phase 1** | ✅ Complete | Feature Engineering (24 base + 23 enhanced features) | 46 |
| **Phase 2** | ✅ Complete | GBRT Models (P10/P50/P90) | 37 |
| **Phase 3** | ✅ Complete | Ensemble Forecaster | 13 |
| **Phase 4** | ✅ Complete | Production API & Monitoring | 9 |
| **Phase 5** | ✅ Complete | Evaluation Framework | 15 |
| **Phase 6** | ✅ Complete | Code Cleanup | 20 |
| **Phase 7** | ✅ Complete | Model Enhancements | 48 |
| **Total** | **100%** | **6 modules, 15+ scripts, 8 configs** | **113+** |

**Key Achievements:**
- ✅ Full ML forecasting pipeline operational
- ✅ Production API deployed (6 endpoints)
- ✅ Monitoring infrastructure ready (15+ metrics, 11 panels)
- ✅ Evaluation tools operational (A/B testing, drift detection)
- ✅ 113+ tests passing (100% success rate)
- ✅ ~6,000+ lines of production code
- ✅ ~2,500+ lines of documentation

### 📋 What's Next?

**See [ML_ARM_NEXT_STEPS.md](ML_ARM_NEXT_STEPS.md) for comprehensive post-implementation guidance:**

- **Phase 8:** Production Deployment & Stabilization (2-4 weeks)
- **Phase 9:** Performance Optimization (3-6 weeks)
- **Phase 10:** Continuous Improvement & Monitoring (Ongoing)
- **Phase 11-13:** Advanced Enhancements & Strategic Initiatives (6-12 months)

---

## Quick Start

### Generate Training Dataset

```bash
python scripts/ml/generate_training_dataset.py \
    --index NIFTY \
    --days 60 \
    --output data/ml/training/nifty_tp_features_60d.csv \
    --compute-baseline \
    --validate
```

### Validate Dataset

```bash
python scripts/ml/validate_features.py \
    --dataset data/ml/training/nifty_tp_features_60d.csv \
    --min-completeness 0.9 \
    --min-correlation 0.85
```

### Use Feature Engineering API

```python
from src.analytics.ml.feature_engineering import FeatureEngineer
from src.analytics.ml.baseline import baseline_tp_batch, compute_residuals
import pandas as pd

# Load data
df = pd.read_csv("historical_data.csv")

# Compute baseline and residuals
df = baseline_tp_batch(df, iv_col="avg_iv")
df = compute_residuals(df)

# Extract features
fe = FeatureEngineer()
df = fe.extract_features(df)

# Validate
is_valid, issues = fe.validate_features(df)
print(f"Valid: {is_valid}")
```

---

## Architecture

### Feature Engineering Pipeline

```
Raw TP Data
    ↓
Baseline Computation (structural formula)
    ↓
Residual Calculation
    ↓
Feature Extraction (24 features)
    ↓
Validation
    ↓
Training Dataset
```

### Features (24 Total)

**Lag Features (12):**
- 6 residual lags (t-1, t-2, t-5, t-10, t-30, t-60)
- 3 rolling means (5min, 15min, 30min)
- 3 rolling stds (5min, 15min, 30min)

**Market Features (8):**
- 2 price returns (1min, 5min)
- 2 IV metrics (level, change)
- 4 time features (expiry, time-of-day, weekday)

**Regime Features (4):**
- 2 volatility percentiles
- 2 placeholders (volume, OI)

---

## Directory Structure

```
docs/ml/
├── README.md (this file)
├── FEATURE_ENGINEERING_GUIDE.md
├── PHASE1_COMPLETION_SUMMARY.md
└── ML_ARM_IMPLEMENTATION_ROADMAP.md

src/analytics/ml/
├── baseline.py (enhanced with batch processing)
├── conformal.py
├── feature_engineering.py (NEW)
├── kalman.py
└── quantile.py

scripts/ml/
├── generate_training_dataset.py (NEW)
├── validate_features.py (NEW)
└── [other ML scripts]

tests/ml/
├── test_baseline_tp.py (enhanced)
├── test_dataset_generation.py (NEW)
├── test_feature_engineering.py (NEW)
└── [other ML tests]

configs/ml/
├── nifty_tp_forecast_gbrt_quantile.json (NEW)
└── banknifty_tp_forecast_gbrt_quantile.json (NEW)

data/ml/training/ (excluded from git)
├── nifty_tp_features_60d.csv
├── nifty_tp_features_60d_stats.json
└── nifty_tp_features_60d_validation.txt
```

---

## Key Concepts

### Baseline TP Formula

The structural baseline captures the fundamental relationships:

```
baseline_tp = k * underlying * avg_iv * sqrt(T)
```

Where:
- `k`: Scaling coefficient (typically 1.0)
- `underlying`: Index spot price
- `avg_iv`: Average implied volatility (decimal)
- `T`: Time to expiry in trading days

### Residual Forecasting

Instead of forecasting TP directly, we forecast the residual:

```
tp_residual = tp_actual - baseline_tp
```

This approach:
- Removes structural dependencies
- Creates a more stationary target
- Improves model performance
- Simplifies feature engineering

### Quantile Regression

We train three separate GBRT models for quantiles:
- P10 (10th percentile) - Lower bound
- P50 (50th percentile) - Median forecast
- P90 (90th percentile) - Upper bound

This provides:
- Point forecasts (P50)
- Uncertainty bands (P10-P90)
- Asymmetric forecasts (if needed)

---

## Testing

Run all ML tests:

```bash
pytest tests/ml/ -v
```

Run specific test modules:

```bash
pytest tests/ml/test_feature_engineering.py -v
pytest tests/ml/test_dataset_generation.py -v
pytest tests/ml/test_baseline_tp.py -v
```

**Test Coverage:**
- 46 total tests
- 100% pass rate
- <4 second execution

---

## Configuration

### Feature Engineering

Customize feature extraction:

```python
from src.analytics.ml.feature_engineering import FeatureEngineer

fe = FeatureEngineer(
    lag_periods=[1, 2, 5, 10, 30, 60],
    rolling_windows=[5, 15, 30],
    price_return_windows=[1, 5],
    min_minutes_to_expiry=1.0,
    max_minutes_to_expiry=375.0,
)
```

### Baseline Computation

Tune baseline coefficient:

```python
from src.analytics.ml.baseline import baseline_tp_batch

df = baseline_tp_batch(
    df,
    k=1.0,  # Adjust if correlation < 0.85
    min_iv=1e-4,
    min_T_minutes=1.0,
)
```

### Model Training (Phase 2)

Training configurations in `configs/ml/`:
- `nifty_tp_forecast_gbrt_quantile.json`
- `banknifty_tp_forecast_gbrt_quantile.json`

---

## Performance

### Dataset Generation

| Operation | Time (60 days) | Memory |
|-----------|----------------|--------|
| Synthetic data | 0.1s | <50MB |
| Baseline | 0.01s | <10MB |
| Features | 4.5s | <400MB |
| Validation | 0.5s | <100MB |
| **Total** | **~5s** | **<500MB** |

### Feature Extraction

- ~15ms per 1,000 samples
- Linear scaling with data size
- Efficient vectorized operations

---

## Best Practices

### Data Quality

1. **Always validate** datasets before training
2. **Check baseline correlation** (target: >0.85)
3. **Review feature distributions** for anomalies
4. **Handle missing data** appropriately

### Feature Engineering

1. **Keep features interpretable** for debugging
2. **Document feature meanings** in code
3. **Test edge cases** (start of day, near expiry)
4. **Update placeholders** when real data available

### Model Training

1. **Use cross-validation** to prevent overfitting
2. **Monitor feature importance** over time
3. **Track model performance** across regimes
4. **Retrain regularly** (weekly recommended)

---

## Troubleshooting

### Low Baseline Correlation

**Problem:** Baseline correlation < 0.85

**Solutions:**
1. Tune k coefficient
2. Check IV data quality
3. Verify time to expiry calculation
4. Review underlying price data

### High NaN Counts

**Problem:** Many NaN values in features

**Solutions:**
1. Skip initial lag period (first 60 samples)
2. Check input data completeness
3. Consider forward-fill for small gaps
4. Review feature computation logic

### Memory Issues

**Problem:** Out of memory during generation

**Solutions:**
1. Process in smaller batches
2. Use fewer days initially
3. Reduce precision (float32)
4. Process indices separately

---

## Contributing

### Adding New Features

1. Add feature extraction to `FeatureEngineer` class
2. Update `get_feature_names()` method
3. Add tests to `test_feature_engineering.py`
4. Update documentation
5. Regenerate datasets

### Adding Tests

1. Place tests in `tests/ml/`
2. Follow existing naming conventions
3. Include docstrings
4. Test edge cases
5. Ensure <1s execution time per test

---

## References

### Internal Documentation

- [Feature Engineering Guide](FEATURE_ENGINEERING_GUIDE.md)
- [Phase 1 Summary](PHASE1_COMPLETION_SUMMARY.md)
- [Implementation Roadmap](ML_ARM_IMPLEMENTATION_ROADMAP.md)

### External Resources

- scikit-learn Quantile Regression: https://scikit-learn.org/stable/modules/ensemble.html#gradient-boosting
- Conformal Prediction: Vovk et al. (2005)
- Time Series Cross-Validation: scikit-learn TimeSeriesSplit

---

## Support

**Questions or Issues?**

1. Check documentation in `docs/ml/`
2. Review test examples in `tests/ml/`
3. Open issue in GitHub repository
4. Contact ML Engineering Team

---

## Changelog

### 2025-11-16 - Phase 1 Complete

**Added:**
- Feature engineering module (24 features)
- Dataset generation script
- Validation script
- Batch baseline processing
- Comprehensive tests (30 new)
- Documentation (2 guides)

**Generated:**
- NIFTY 60-day dataset
- BANKNIFTY 60-day dataset
- Training configurations

**Status:**
- ✅ All Phase 1 deliverables complete
- ✅ Ready for Phase 2

---

**Last Updated:** 2025-11-16  
**Status:** Phase 1 Complete, Phase 2 In Progress
