# ML ARM Implementation Roadmap
# Comprehensive and Concrete Plan for Recommended Enhancements

**Document Version:** 1.0  
**Date:** 2025-11-16  
**Based On:** `docs/ML_ARM_REFACTORING_ANALYSIS.md`  
**Status:** Active Implementation Plan

---

## Executive Summary

This roadmap provides a concrete, step-by-step implementation plan for the enhancements recommended in `ML_ARM_REFACTORING_ANALYSIS.md`. The goal is to optimize ML capabilities for forecasting ATM Total Premium (TP) through:

1. **Feature Engineering Pipeline** - Extract and prepare features for ML models
2. **Quantile GBRT Training** - Train supervised residual forecasting models
3. **Ensemble Integration** - Combine baseline, GBRT, and retrieval forecasters
4. **Production Deployment** - Deploy models with monitoring and alerting
5. **Code Cleanup** - Remove deprecated code and improve maintainability

**Timeline:** 5-6 weeks  
**Priority:** High  
**Dependencies:** Existing data collection infrastructure, path forecasting framework

---

## Current State Assessment

### ✅ Available Components
- **Data Collection**: Robust provider/collector architecture with minute-level TP data
- **Baseline Model**: `src/analytics/ml/baseline.py` - Structural TP formula
- **Kalman Filter**: `src/analytics/ml/kalman.py` - Smoothing capabilities
- **Quantile Regressor**: `src/analytics/ml/quantile.py` - GBRT framework exists
- **Conformal Prediction**: `src/analytics/ml/conformal.py` - Uncertainty quantification
- **Retrieval Forecaster**: `src/path_forecast/retrieval.py` - K-NN historical matching
- **Composite Forecaster**: `src/path_forecast/composite.py` - Blending logic
- **Test Infrastructure**: Comprehensive test suite in `tests/ml/`

### ⚠️ Gaps to Address
- No integrated feature engineering pipeline for ML models
- Quantile GBRT not trained or integrated into production forecasting
- No ensemble combination logic with confidence-based weighting
- Hybrid forecaster is a stub (`src/path_forecast/hybrid.py`)
- Missing production deployment scripts and monitoring dashboards
- Legacy code requiring cleanup

---

## Implementation Phases Overview

| Phase | Focus | Duration | Priority | Dependencies |
|-------|-------|----------|----------|--------------|
| **Phase 1** | Feature Engineering & Data Prep | 1-2 weeks | Critical | Historical data (60 days) |
| **Phase 2** | GBRT Model Training | 1 week | Critical | Phase 1 complete |
| **Phase 3** | Ensemble Integration | 1 week | High | Phases 1-2 complete |
| **Phase 4** | Production Deployment | 1 week | High | Phases 1-3 complete |
| **Phase 5** | Evaluation & Improvement | Ongoing | Medium | Phase 4 complete |
| **Phase 6** | Code Cleanup | 1 week | Medium | Can run in parallel |

---

## Phase 1: Feature Engineering and Data Preparation

**Duration:** 1-2 weeks  
**Priority:** Critical  
**Owner:** ML Engineering Team

### Objectives
- Create reusable feature extraction pipeline
- Generate training dataset with 60 days of historical data
- Compute baseline TP and residuals
- Validate data quality and feature coverage

### Deliverables

#### 1.1 Feature Engineering Module
**File:** `src/analytics/ml/feature_engineering.py`

**Key Features to Extract (24 total):**

1. **Lag Features (12):**
   - TP residual lags: t-1, t-2, t-5, t-10, t-30, t-60
   - Rolling mean residuals: 5min, 15min, 30min
   - Rolling std residuals: 5min, 15min, 30min

2. **Market Features (8):**
   - Index price return (1min, 5min)
   - Avg IV level and change (1min)
   - Minutes to expiry (normalized)
   - Time-of-day (sin/cos encoding)
   - Weekday (ordinal)

3. **Regime Features (4):**
   - IV percentile (0-1 scale)
   - Index volatility percentile
   - Volume ratio (current vs. daily avg)
   - OI change rate

**Implementation Tasks:**
- [ ] Design `FeatureEngineer` class interface
- [ ] Implement lag feature extraction
- [ ] Implement rolling statistics
- [ ] Implement market feature extraction
- [ ] Implement regime feature extraction
- [ ] Add feature validation and quality checks
- [ ] Write comprehensive unit tests

#### 1.2 Dataset Generation Script
**File:** `scripts/ml/generate_training_dataset.py`

```bash
# Usage Example
python scripts/ml/generate_training_dataset.py \
    --index NIFTY \
    --days 60 \
    --output data/ml/training/nifty_tp_features_60d.csv \
    --compute-baseline \
    --validate
```

**Output Files:**
- `data/ml/training/nifty_tp_features_60d.csv` - Feature matrix
- `data/ml/training/nifty_tp_features_60d_stats.json` - Data quality report
- `data/ml/training/nifty_tp_features_60d_validation.txt` - Validation report

#### 1.3 Baseline Enhancement
**File:** `src/analytics/ml/baseline.py` (enhance existing)

Add batch processing:
- Read TP data from CSV
- Compute: `baseline_tp = k * index_price * avg_iv * sqrt(T)`
- Compute residuals: `tp_residual = tp_actual - baseline_tp`
- Write enhanced CSV with baseline and residual columns

### Week-by-Week Implementation

#### Week 1: Feature Engineering Module
**Day 1-2: Design & Architecture**
- [ ] Review ML_ARM_REFACTORING_ANALYSIS.md Section 5.2
- [ ] Design `FeatureEngineer` class interface
- [ ] Document feature definitions and rationale
- [ ] Create feature extraction plan

**Day 3-4: Implementation**
- [ ] Implement lag features
- [ ] Implement rolling statistics
- [ ] Implement market features
- [ ] Implement regime features
- [ ] Add input validation

**Day 5: Testing**
- [ ] Write unit tests for each feature function
- [ ] Validate feature ranges and distributions
- [ ] Test edge cases (missing data, early session)
- [ ] Code review

#### Week 2: Dataset Generation
**Day 1-2: Script Development**
- [ ] Implement CSV reading and parsing
- [ ] Implement feature matrix construction
- [ ] Integrate baseline TP computation
- [ ] Add residual calculation

**Day 3: Data Quality Validation**
- [ ] Check for NaN/Inf values
- [ ] Validate feature distributions
- [ ] Check for data leakage
- [ ] Verify temporal ordering

**Day 4: Dataset Generation**
- [ ] Generate NIFTY 60-day dataset
- [ ] Generate BANKNIFTY 60-day dataset
- [ ] Document dataset statistics
- [ ] Store datasets securely

**Day 5: Review & Documentation**
- [ ] Complete feature engineering documentation
- [ ] Create data quality report
- [ ] Final code review
- [ ] Prepare for Phase 2

### Success Criteria
- [ ] Feature extraction produces 24 features per sample
- [ ] Training dataset covers 60 days with >90% completeness
- [ ] Baseline TP correlation with actual TP > 0.85
- [ ] Zero NaN/Inf values in feature matrix
- [ ] Feature distributions are reasonable
- [ ] All tests pass with >80% coverage

### Testing Strategy
```bash
# Unit tests
pytest tests/ml/test_feature_engineering.py -v

# Integration tests
pytest tests/ml/test_dataset_generation.py -v

# Validation tests
python scripts/ml/validate_features.py --dataset data/ml/training/nifty_tp_features_60d.csv
```

### Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Insufficient historical data | High | Start with 30-day minimum if needed |
| Data quality issues | Medium | Robust filtering and imputation |
| Feature computation errors | High | Comprehensive unit tests |
| Memory issues | Medium | Batch processing |

---

## Phase 2: GBRT Model Training

**Duration:** 1 week  
**Priority:** Critical  
**Owner:** ML Engineering Team

### Objectives
- Configure and train Quantile GBRT models
- Perform hyperparameter tuning
- Validate using walk-forward cross-validation
- Save trained model artifacts

### Deliverables

#### 2.1 Training Configuration
**File:** `configs/ml/nifty_tp_forecast_gbrt_quantile.json`

```json
{
  "model_type": "quantile_gbrt",
  "index": "NIFTY",
  "target": "tp_residual",
  "quantiles": [0.1, 0.5, 0.9],
  "hyperparameters": {
    "n_estimators": 500,
    "max_depth": 4,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "max_features": "sqrt",
    "min_samples_leaf": 10,
    "random_state": 42
  },
  "training": {
    "train_days": 45,
    "val_days": 5,
    "cv_folds": 5
  }
}
```

#### 2.2 Training Script
**File:** `scripts/ml/train_gbrt_quantile.py`

```bash
python scripts/ml/train_gbrt_quantile.py \
    --config configs/ml/nifty_tp_forecast_gbrt_quantile.json \
    --dataset data/ml/training/nifty_tp_features_60d.csv \
    --output models/nifty_gbrt_quantile/ \
    --tune-hyperparams
```

**Outputs:**
- `models/nifty_gbrt_quantile/model_q10.joblib`
- `models/nifty_gbrt_quantile/model_q50.joblib`
- `models/nifty_gbrt_quantile/model_q90.joblib`
- `models/nifty_gbrt_quantile/feature_engineering.json`
- `models/nifty_gbrt_quantile/training_report.json`

#### 2.3 Hyperparameter Tuning
**File:** `scripts/ml/tune_gbrt_hyperparams.py`

**Search Space:**
- `n_estimators`: [300, 500, 700]
- `max_depth`: [3, 4, 5]
- `learning_rate`: [0.02, 0.03, 0.05]
- `subsample`: [0.7, 0.8, 0.9]

**Objective:** Minimize validation MAE for P50 + average pinball loss

### Week Implementation

**Day 1: Setup**
- [ ] Enhance `src/analytics/ml/quantile.py` with batch training
- [ ] Create training configuration files
- [ ] Setup model artifact storage

**Day 2: Training**
- [ ] Load and validate training data
- [ ] Split data (train/validation)
- [ ] Train three quantile models
- [ ] Compute training metrics

**Day 3: Hyperparameter Tuning**
- [ ] Implement grid search
- [ ] Run hyperparameter optimization
- [ ] Analyze results
- [ ] Select best configuration

**Day 4: Validation**
- [ ] Implement time-series cross-validation
- [ ] Test on held-out data
- [ ] Compute evaluation metrics

**Day 5: Analysis & Documentation**
- [ ] Analyze feature importance
- [ ] Generate training reports
- [ ] Document model configuration
- [ ] Code review

### Success Criteria
- [ ] Three quantile models trained (P10, P50, P90)
- [ ] P50 MAE < 5% of mean TP
- [ ] Empirical coverage 75-85%
- [ ] Feature importance analysis complete
- [ ] Models serialize/deserialize correctly

### Evaluation Metrics

**Point Forecast (P50):**
- MAE, RMSE, MAPE, Correlation

**Quantile Forecast (P10/P90):**
- Pinball Loss
- Empirical Coverage
- Average Band Width
- Calibration (symmetry)

**Feature Analysis:**
- Feature Importance (GBRT native)
- Top 15 Features identification
- Feature Stability across folds

---

## Phase 3: Ensemble Integration

**Duration:** 1 week  
**Priority:** High  
**Owner:** ML Engineering Team

### Objectives
- Implement ensemble combination logic
- Add confidence-based weighting
- Integrate conformal calibration
- Test end-to-end pipeline

### Deliverables

#### 3.1 Ensemble Forecaster Module
**File:** `src/path_forecast/ensemble.py`

**Key Components:**
- `EnsembleForecaster` class
- Confidence computation logic
- Adaptive weighting strategy
- Conformal calibration integration

#### 3.2 Ensemble Configuration
**File:** `configs/ml/nifty_ensemble_config.json`

```json
{
  "ensemble_type": "hybrid_adaptive",
  "components": {
    "baseline": {"enabled": true, "k_coefficient": 1.0},
    "gbrt": {"enabled": true, "model_path": "models/nifty_gbrt_quantile/"},
    "retrieval": {"enabled": true, "k": 20, "window": 60},
    "conformal": {"enabled": true, "target_coverage": 0.8, "window": 600}
  },
  "weighting": {
    "strategy": "confidence_adaptive",
    "weights_high_conf": {"gbrt": 0.8, "retrieval": 0.2},
    "weights_low_conf": {"gbrt": 0.5, "retrieval": 0.5}
  }
}
```

#### 3.3 Ensemble Serving Script
**File:** `scripts/ml/run_ensemble_forecaster.py`

```bash
python scripts/ml/run_ensemble_forecaster.py \
    --config configs/ml/nifty_ensemble_config.json \
    --index NIFTY \
    --output data/ml/live_predictions/nifty_ensemble.csv \
    --interval 60
```

### Week Implementation

**Day 1-2: Implementation**
- [ ] Design `EnsembleForecaster` class
- [ ] Implement confidence computation
- [ ] Implement adaptive weighting
- [ ] Implement forecast combination

**Day 3: Integration Testing**
- [ ] Test baseline + GBRT integration
- [ ] Test full ensemble pipeline
- [ ] Test conformal calibration
- [ ] Test end-to-end forecasting

**Day 4: Confidence & Weighting**
- [ ] Implement GBRT confidence metrics
- [ ] Implement retrieval confidence metrics
- [ ] Test adaptive weighting scenarios
- [ ] Validate weight transitions

**Day 5: Documentation**
- [ ] Document ensemble architecture
- [ ] Create operational guide
- [ ] Code review and optimization
- [ ] Prepare for deployment

### Forecast Pipeline Flow

```
Input: Current TP, Index Price, IV, Time
  ↓
1. Baseline: TP_baseline = k * price * iv * sqrt(T)
  ↓
2. GBRT Residual Forecast → Quantiles(P10, P50, P90)
  ↓
3. Retrieval Residual Forecast → Quantiles(P10, P50, P90)
  ↓
4. Confidence: f(gbrt_oob, retrieval_k, regime_match)
  ↓
5. Adaptive Weighting: w_gbrt, w_retr = get_weights(confidence)
  ↓
6. Combine: residual[q] = w_gbrt * GBRT[q] + w_retr * Retrieval[q]
  ↓
7. Add Baseline: TP[q] = TP_baseline + residual[q]
  ↓
8. Conformal Calibration → Final bands
  ↓
Output: TP_forecast [P10, P50, P90, band_low, band_high]
```

### Success Criteria
- [ ] Ensemble produces P10/P50/P90 quantiles
- [ ] Confidence-based weighting works correctly
- [ ] Conformal bands provide ~80% coverage
- [ ] End-to-end latency < 1 second
- [ ] All integration tests pass

---

## Phase 4: Production Deployment

**Duration:** 1 week  
**Priority:** High  
**Owner:** MLOps Team

### Objectives
- Deploy ensemble forecaster as a service
- Setup monitoring and alerting
- Create Grafana dashboards
- Implement automated retraining

### Deliverables

#### 4.1 Model Serving API
**File:** `src/web/api/ml_ensemble.py`

**Endpoints:**
- `GET /api/ml/ensemble/forecast?index=NIFTY&horizon=60`
- `GET /api/ml/ensemble/diagnostics?index=NIFTY`
- `GET /api/ml/ensemble/confidence?index=NIFTY`
- `POST /api/ml/ensemble/retrain`

#### 4.2 Prometheus Metrics

```
g6_ml_ensemble_forecast_p10{index,horizon}
g6_ml_ensemble_forecast_p50{index,horizon}
g6_ml_ensemble_forecast_p90{index,horizon}
g6_ml_ensemble_confidence{index}
g6_ml_ensemble_weight_gbrt{index}
g6_ml_ensemble_weight_retrieval{index}
g6_ml_ensemble_latency_seconds{index,component}
g6_ml_ensemble_mae_p50{index}
g6_ml_ensemble_coverage_actual{index}
g6_ml_ensemble_conformal_radius{index}
```

#### 4.3 Grafana Dashboard
**File:** `grafana/dashboards/ml_ensemble_monitoring.json`

**Panels:**
1. Real-time TP forecast (P10/P50/P90 bands)
2. Actual vs. forecasted TP overlay
3. Residual distribution
4. Coverage percentage (rolling window)
5. Confidence score timeline
6. Component weights
7. Model latency histogram
8. Feature importance heatmap
9. Conformal radius timeline
10. Alert status

#### 4.4 Alerting Rules
**File:** `prometheus_rules_ml_ensemble.yml`

**Key Alerts:**
- `MLEnsembleUnderCoverage` - Coverage < 75% for 15m
- `MLEnsemblePersistentUnderCoverage` - Coverage < 70% for 30m
- `MLEnsembleHighLatency` - P95 latency > 2s for 5m
- `MLEnsembleForecastError` - Error rate > 10%
- `MLEnsembleModelStale` - Model age > 14 days

#### 4.5 Automated Retraining
**File:** `scripts/ml/automated_retraining.py`

```bash
# Cron: Every Sunday at 2 AM
0 2 * * 0 python scripts/ml/automated_retraining.py --index NIFTY --days 60
```

**Retraining Flow:**
1. Fetch last 60 days of data
2. Generate training dataset
3. Train GBRT models
4. Validate on last 5 days
5. Compare with production model
6. If improvement > 5%, promote to production
7. Archive old model
8. Send notification

### Week Implementation

**Day 1: Serving Infrastructure**
- [ ] Implement API endpoints
- [ ] Setup model loading and caching
- [ ] Add request/response validation
- [ ] Test API functionality

**Day 2: Metrics Integration**
- [ ] Implement Prometheus exporters
- [ ] Test metrics collection
- [ ] Verify in Prometheus
- [ ] Document metrics

**Day 3: Dashboard Creation**
- [ ] Design dashboard layout
- [ ] Create forecast panels
- [ ] Create diagnostics panels
- [ ] Create alert panels

**Day 4: Alerting Setup**
- [ ] Configure alert rules
- [ ] Test alert firing
- [ ] Setup Alertmanager routing
- [ ] Configure notifications

**Day 5: Retraining Automation**
- [ ] Implement retraining script
- [ ] Setup cron job
- [ ] Test retraining pipeline
- [ ] Document procedures

### Success Criteria
- [ ] API responds within 1 second
- [ ] Metrics update every 60 seconds
- [ ] Dashboards render correctly
- [ ] Alerts fire under test conditions
- [ ] Retraining completes successfully
- [ ] Zero-downtime deployment

### Operational Runbook

#### Start Service:
```bash
python scripts/ml/run_ensemble_forecaster.py \
    --config configs/ml/nifty_ensemble_config.json \
    --index NIFTY \
    --daemon
```

#### Monitor Status:
```bash
curl http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY
```

#### View Logs:
```bash
tail -f logs/ml_ensemble.log
```

#### Troubleshooting:

**Under-coverage (<75%):**
- Check conformal window size
- Check for regime shifts
- Adjust coverage target

**High latency (>2s):**
- Check retrieval cache hit rate
- Profile component latencies
- Check system resources

**Poor accuracy:**
- Check if model is stale
- Review market regime
- Trigger manual retraining

#### Emergency Fallbacks:

**Retrieval-only mode:**
```bash
python scripts/ml/run_ensemble_forecaster.py --disable-gbrt --index NIFTY
```

**Baseline-only mode:**
```bash
python scripts/ml/run_baseline_forecaster.py --index NIFTY
```

---

## Phase 5: Evaluation & Continuous Improvement

**Duration:** Ongoing  
**Priority:** Medium  
**Owner:** ML Engineering + MLOps Teams

### Objectives
- A/B test ensemble vs. retrieval-only
- Monitor performance across regimes
- Periodic retraining and tuning
- Feature importance analysis
- Continuous optimization

### Key Activities

#### A/B Testing
**File:** `scripts/ml/ab_test_ensemble.py`

```bash
python scripts/ml/ab_test_ensemble.py \
    --index NIFTY \
    --variant-a ensemble \
    --variant-b retrieval_only \
    --duration-days 7
```

**Compare:**
- MAE, RMSE, MAPE
- Coverage accuracy
- Latency
- Confidence stability

#### Regime-Specific Evaluation
**File:** `scripts/ml/evaluate_by_regime.py`

```bash
python scripts/ml/evaluate_by_regime.py \
    --index NIFTY \
    --days 30 \
    --regimes high_vol,low_vol,trending,sideways
```

**Regime Definitions:**
- High Volatility: IV > 80th percentile
- Low Volatility: IV < 20th percentile
- Trending: Directional move > 1% per hour
- Sideways: Directional move < 0.3% per hour

#### Feature Importance Tracking
```bash
python scripts/ml/track_feature_importance.py \
    --model models/nifty_gbrt_quantile/ \
    --output reports/feature_importance_weekly.html
```

#### Model Drift Detection
```bash
python scripts/ml/detect_model_drift.py \
    --index NIFTY \
    --baseline-period 30d \
    --test-period 7d \
    --alert-threshold 0.15
```

**Drift Indicators:**
- MAE degradation > 15%
- Coverage drift > 5%
- Feature distribution shifts
- Residual bias

### Success Criteria
- [ ] Ensemble improvement ≥ 5% vs. retrieval-only
- [ ] Performance stable across regimes
- [ ] Feature importance stable
- [ ] Drift detected proactively
- [ ] Continuous MAE improvement

---

## Phase 6: Code Cleanup & Maintenance

**Duration:** 1 week  
**Priority:** Medium  
**Owner:** Engineering Team

### Objectives
- Remove deprecated code
- Consolidate duplicate utilities
- Improve exception handling
- Enhance documentation
- Reduce technical debt

### Cleanup Tasks

#### 6.1 Remove Deprecated Code

**Legacy Web Dashboard:**
```bash
rm -rf src/web/dashboard/
# Update documentation to point to Grafana
```

**Archived Code:**
```bash
# Keep last 2 release cycles
cd archive/ && ls -t | tail -n +3 | xargs rm -rf
```

**Old Model Checkpoints:**
```bash
find models/ -name "*.old" -o -name "*.backup" -mtime +90 -delete
```

#### 6.2 Consolidate Duplicate Utilities

**TP Extraction Functions:**
- Consolidate in `src/path_forecast/common.py`
- Remove from `src/storage/csv_utils.py`
- Remove from `src/web/dashboard/core/csv_io.py`

**Timestamp Parsing:**
- Centralize in `src/utils/time_utils.py`
- Update all callers

#### 6.3 Improve Exception Handling

Replace broad `except Exception: pass` with:
```python
try:
    result = risky_operation()
except SpecificError as e:
    logger.error(f"Failed: {e}", exc_info=True)
    raise
except RecoverableError as e:
    logger.warning(f"Recoverable: {e}")
    result = fallback_value
```

**Files to update:**
- `src/path_forecast/retrieval.py`
- `src/path_forecast/composite.py`
- `src/web/api/ml_ensemble.py`

#### 6.4 Centralize Magic Numbers

**File:** `src/path_forecast/params.py` (enhance)

```python
# Ensemble Parameters
ENSEMBLE_HIGH_CONFIDENCE_THRESHOLD = 0.7
ENSEMBLE_WEIGHT_GBRT_HIGH_CONF = 0.8
ENSEMBLE_WEIGHT_RETRIEVAL_HIGH_CONF = 0.2

# Conformal Parameters
CONFORMAL_DEFAULT_COVERAGE = 0.8
CONFORMAL_DEFAULT_WINDOW = 600

# Retrieval Parameters
RETRIEVAL_DEFAULT_K = 20
RETRIEVAL_DEFAULT_WINDOW = 60

# Baseline Parameters
BASELINE_K_COEFFICIENT = 1.0
```

#### 6.5 Expand Test Coverage

**New test files:**
- `tests/ml/test_retrieval_edge_cases.py`
- `tests/ml/test_composite_blending.py`
- `tests/ml/test_conformal_coverage.py`
- `tests/ml/test_ensemble_fallbacks.py`

**Test scenarios:**
- No historical candidates
- Single candidate
- Extreme volatility
- Missing features
- Model loading failures
- API timeouts

### Week Implementation

**Day 1: Remove Deprecated**
- [ ] Remove legacy dashboard
- [ ] Prune old archives
- [ ] Remove old checkpoints
- [ ] Update docs

**Day 2: Consolidate Utilities**
- [ ] Audit duplicate functions
- [ ] Consolidate TP extraction
- [ ] Update imports
- [ ] Test changes

**Day 3: Exception Handling**
- [ ] Audit broad exception handlers
- [ ] Replace with specific exceptions
- [ ] Add structured logging
- [ ] Test error scenarios

**Day 4: Centralize Parameters**
- [ ] Identify hardcoded values
- [ ] Move to params.py
- [ ] Update references
- [ ] Add validation

**Day 5: Expand Tests**
- [ ] Write edge case tests
- [ ] Achieve >80% coverage
- [ ] Document scenarios
- [ ] Code review

### Success Criteria
- [ ] All deprecated code removed
- [ ] No duplicate utilities
- [ ] Specific exception handling
- [ ] No magic numbers
- [ ] Test coverage > 80%
- [ ] Documentation updated

### Documentation Updates

**Files to Update:**
- `docs/ML_ARM_QUICKSTART.md`
- `docs/ml/ML_ARM_USER_GUIDE.md`
- `docs/ml/ML_README.md`
- `README.md`

**New Documentation:**
- `docs/ml/ENSEMBLE_GUIDE.md`
- `docs/ml/FEATURE_ENGINEERING_GUIDE.md`
- `docs/ml/MODEL_TRAINING_RUNBOOK.md`
- `docs/ml/PRODUCTION_DEPLOYMENT_CHECKLIST.md`

---

## Success Metrics Summary

### Technical Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| MAE (P50) | < 5% of mean TP | Daily average |
| Coverage (P10-P90) | 75-85% | Rolling 1-day |
| Latency | < 1 second | P95 per forecast |
| Uptime | > 95% | Monthly |
| Test Coverage | > 80% | Per commit |

### Business Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| Forecast Horizon | 375 minutes | Full market day |
| Update Frequency | 30-60 seconds | Real-time |
| Fallback Rate | < 1% | Monthly |
| Model Staleness | < 14 days | Continuous |

### Operational Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| Deployment Time | < 10 minutes | Per deployment |
| Retraining Time | < 2 hours | Weekly |
| MTTR | < 30 minutes | Per incident |
| Alert FP Rate | < 5% | Monthly |

---

## Timeline & Milestones

### Week 1-2: Phase 1 - Feature Engineering
- **Milestone 1.1** (Day 5): Feature module complete
- **Milestone 1.2** (Day 10): Datasets generated

### Week 3: Phase 2 - GBRT Training
- **Milestone 2.1** (Day 15): Models trained
- **Milestone 2.2** (Day 17): Hyperparams tuned

### Week 4: Phase 3 - Ensemble Integration
- **Milestone 3.1** (Day 20): Ensemble implemented
- **Milestone 3.2** (Day 24): E2E testing complete

### Week 5: Phase 4 - Production Deployment
- **Milestone 4.1** (Day 27): API deployed
- **Milestone 4.2** (Day 31): Monitoring operational

### Week 6: Phase 6 - Code Cleanup
- **Milestone 6.1** (Day 34): Deprecated removed
- **Milestone 6.2** (Day 38): Docs updated

### Ongoing: Phase 5 - Evaluation
- **Monthly Review**: Performance evaluation

---

## Risk Register

### High-Priority Risks
| Risk ID | Risk | Probability | Impact | Mitigation |
|---------|------|-------------|--------|------------|
| R1 | Insufficient data | Medium | High | Start with 30-day minimum |
| R2 | GBRT overfitting | Medium | High | Cross-validation, regularization |
| R3 | Service failure | Low | Critical | Health checks, fallbacks |
| R4 | Model staleness | Medium | Medium | Automated retraining |

### Medium-Priority Risks
| Risk ID | Risk | Probability | Impact | Mitigation |
|---------|------|-------------|--------|------------|
| R5 | Feature bugs | Medium | Medium | Comprehensive testing |
| R6 | Latency spikes | Low | Medium | Profiling, caching |
| R7 | Coverage miscalibration | Medium | Medium | Conformal calibration |
| R8 | Breaking changes | Low | Medium | Gradual rollout |

---

## Dependencies & Prerequisites

### Technical Dependencies
- Python 3.8+
- scikit-learn >= 1.0
- pandas >= 1.3
- numpy >= 1.21
- joblib >= 1.0
- lightgbm >= 3.3 (or catboost >= 1.0)
- optuna >= 2.10

### Infrastructure
- Prometheus for metrics
- Grafana for dashboards
- Alertmanager for alerting
- Storage for model artifacts (~500MB per model)

### Data Prerequisites
- [ ] 60 days historical TP data (minimum 30)
- [ ] Minute-level granularity
- [ ] Index price, IV, Greeks available
- [ ] Data quality >90% completeness

### Team Prerequisites
- [ ] ML Engineer(s) with Python/scikit-learn
- [ ] MLOps Engineer for deployment
- [ ] Data Engineer for pipeline
- [ ] DevOps support

---

## Appendices

### Appendix A: Key Files

**Source Code:**
- `src/analytics/ml/baseline.py`
- `src/analytics/ml/quantile.py`
- `src/analytics/ml/conformal.py`
- `src/analytics/ml/feature_engineering.py` (NEW)
- `src/path_forecast/ensemble.py` (NEW)
- `src/path_forecast/retrieval.py`
- `src/path_forecast/common.py`
- `src/path_forecast/params.py`

**Scripts:**
- `scripts/ml/generate_training_dataset.py` (NEW)
- `scripts/ml/train_gbrt_quantile.py` (NEW)
- `scripts/ml/tune_gbrt_hyperparams.py` (NEW)
- `scripts/ml/run_ensemble_forecaster.py` (NEW)
- `scripts/ml/automated_retraining.py` (NEW)

**Configuration:**
- `configs/ml/nifty_tp_forecast_gbrt_quantile.json` (NEW)
- `configs/ml/nifty_ensemble_config.json` (NEW)

**Tests:**
- `tests/ml/test_feature_engineering.py` (NEW)
- `tests/ml/test_gbrt_training.py` (NEW)
- `tests/ml/test_ensemble_forecaster.py` (NEW)

**Documentation:**
- `docs/ml/ML_ARM_IMPLEMENTATION_ROADMAP.md` (This document)
- `docs/ml/ML_ARM_REFACTORING_ANALYSIS.md`
- `docs/ml/ML_ROADMAP_TP_FORECAST.md`
- `docs/ml/ENSEMBLE_GUIDE.md` (NEW)

### Appendix B: Glossary

- **TP** - Total Premium (CE + PE)
- **CE** - Call Option Premium
- **PE** - Put Option Premium
- **ATM** - At The Money
- **IV** - Implied Volatility
- **GBRT** - Gradient Boosting Regression Trees
- **MAE** - Mean Absolute Error
- **RMSE** - Root Mean Squared Error
- **K-NN** - K-Nearest Neighbors
- **Quantile** - Percentile (P10, P50, P90)
- **Conformal Prediction** - Distribution-free uncertainty
- **Pinball Loss** - Quantile regression loss
- **Coverage** - % of actuals within predicted bands

### Appendix C: References

1. ML_ARM_REFACTORING_ANALYSIS.md - Primary analysis
2. ML_ROADMAP_TP_FORECAST.md - Existing ML roadmap
3. scikit-learn Quantile Regression Documentation
4. Conformal Prediction: Vovk et al. (2005)
5. Time Series Cross-Validation: scikit-learn

---

## Contact & Support

**Questions or Issues?**
- Open issue in GitHub repository
- Contact ML Engineering Team
- Refer to `docs/ml/` documentation

**Feedback Welcome:**
This is a living document. Please provide feedback and suggestions.

---

**End of Implementation Roadmap**

_This roadmap provides actionable, measurable, and achievable steps. Each phase builds on the previous one with clear deliverables, success criteria, and risk mitigation. Regular reviews and updates are recommended._
