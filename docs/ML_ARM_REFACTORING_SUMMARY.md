# ML Arm Refactoring Summary

**Quick Reference Document**  
**Date:** 2025-11-16  
**Related:** [ML_ARM_REFACTORING_ANALYSIS.md](ML_ARM_REFACTORING_ANALYSIS.md)

---

## Purpose

This document provides a concise summary of the ML arm refactoring analysis for forecasting ATM Total Premium (TP = ATM CE + ATM PE). For detailed information, see the full [ML Arm Refactoring Analysis](ML_ARM_REFACTORING_ANALYSIS.md).

---

## Key Findings

### ✅ **Data Collection: EXCELLENT**
- Robust provider/collector architecture
- Comprehensive data: TP, IV, Greeks, volume, OI
- Minute-level granularity with archival
- Data quality: Structured CSV, automatic retention, junk filtering

### ✅ **Analytics: STRONG**
- Newton-Raphson IV solver (Black-Scholes)
- Complete Greeks calculation (Delta, Gamma, Vega, Theta, Rho)
- Supporting indicators (PCR, volatility surface planned)

### ⚠️ **ML Capabilities: NEEDS OPTIMIZATION**
- Strong foundation: Baseline, Kalman, Retrieval, Conformal
- **Gap**: No trained supervised model integrated (GBRT available but unused)
- Transformer/deep learning planned but not implemented

---

## Current ML Components

| Component | Location | Purpose | Status | Assessment |
|-----------|----------|---------|--------|------------|
| **Baseline** | `src/analytics/ml/baseline.py` | Structural TP formula: `k * price * iv * sqrt(T)` | ✅ Deployed | Fast, interpretable, captures fundamentals |
| **Kalman Filter** | `src/analytics/ml/kalman.py` | 1D state-space smoother | ✅ Available | Good for noise reduction, no predictive power |
| **Quantile GBRT** | `src/analytics/ml/quantile.py` | Gradient boosting quantile regressor | ⚠️ Not integrated | **Strong candidate for residuals** |
| **Conformal** | `src/analytics/ml/conformal.py` | Non-parametric uncertainty bands | ✅ Deployed | Model-agnostic, essential for calibration |
| **Retrieval** | `src/path_forecast/retrieval.py` | K-NN on historical TP windows | ✅ Deployed | Non-parametric, captures regimes |
| **Composite** | `src/path_forecast/composite.py` | Blends median prior + retrieval | ✅ Deployed | Smooth fallback for sparse data |
| **Hybrid** | `src/path_forecast/hybrid.py` | Transformer + retrieval fusion | ❌ Stub only | Planned for Phase 1-2 |

---

## Recommended Architecture

### **Optimal Model: Hybrid Ensemble**

```
Stage 1: Baseline Decomposition
  TP_observed = TP_baseline + TP_residual
  TP_baseline = k * index_price * avg_iv * sqrt(T)

Stage 2: Residual Forecasting (Quantile GBRT)
  Input Features (24 total):
    - TP residual lags: [t-1, t-2, t-5, t-10, t-30, t-60]
    - Rolling stats: mean/std over [5, 15, 30] min windows
    - Market: index returns, IV level/change, minutes to expiry, time-of-day
    - Regime: IV percentile, vol percentile, volume ratio, OI change
  
  Model: GradientBoostingRegressor (quantile loss)
    - Quantiles: [0.1, 0.5, 0.9]
    - n_estimators: 500
    - max_depth: 4
    - learning_rate: 0.03
    - subsample: 0.8

Stage 3: Retrieval Refinement
  Config:
    - k=20, window=60, distance_metric="recent_l2"
    - weight_mode="inv_dist", regime_tolerance=0.3
    - use_ann=True (if available)

Stage 4: Ensemble Combination
  TP_forecast[q] = TP_baseline + w_gbrt*GBRT[q] + w_retr*Retrieval[q]
  
  Confidence-based weighting:
    - High confidence: w_gbrt=0.8, w_retr=0.2
    - Low confidence: w_gbrt=0.5, w_retr=0.5

Stage 5: Conformal Calibration
  Apply ConformalBand for empirical coverage guarantees
  Output: [P10_lower, P10, P50, P90, P90_upper]
```

### **Why This Works**

✅ **Baseline** removes structural trends → focus ML on microstructure  
✅ **GBRT** learns non-linear residual patterns from features  
✅ **Retrieval** handles rare regimes not in training data  
✅ **Conformal** ensures calibrated uncertainty bands  
✅ **Ensemble** combines strengths, provides fallback  

---

## Feature Importance (Expected)

### High Importance
1. TP residual lags (t-1, t-2) — momentum/autocorrelation
2. Avg IV — direct premium impact
3. Index price — structural dependency
4. Minutes to expiry — time decay

### Medium Importance
5. Greeks (Vega, Gamma) — volatility/convexity
6. Volume/OI — liquidity indicators
7. Time-of-day — intraday patterns

### Low Importance
8. Rho — interest rate (negligible for short-dated)
9. Weekday — minor effect

---

## Code Cleanup Recommendations

### Remove / Archive
- ✅ **Old ML modules** (`src/ml_arm/`) — Already removed
- ⚠️ **Legacy web dashboard** (`src/web/dashboard/`) — Marked for removal (R+1)
- ✅ **Archived code** (`external/G6_.archived/`) — Periodic pruning needed

### Consolidate
- ⚠️ **Duplicate TP extraction** — Scattered across modules (partial consolidation done)
- ⚠️ **CSV parsing helpers** — Redundancy in `storage/csv_utils.py` and `web/dashboard/core/csv_io.py`

### Improve
- ⚠️ **Broad exception handling** — Replace `except Exception: pass` with structured logging
- ⚠️ **Magic numbers** — Centralize thresholds in `params.py`
- ⚠️ **Test coverage** — Expand edge case tests (retrieval, composite, conformal)

---

## Implementation Roadmap

| Phase | Duration | Tasks | Priority |
|-------|----------|-------|----------|
| **Phase 1: Data Prep** | 1-2 weeks | Feature extraction, training dataset (60 days), baseline computation | 🔴 High |
| **Phase 2: GBRT Training** | 1 week | Hyperparameter tuning, model training, walk-forward validation | 🔴 High |
| **Phase 3: Ensemble** | 1 week | Combination logic, confidence weighting, conformal calibration | 🔴 High |
| **Phase 4: Deployment** | 1 week | Serving endpoint, retraining schedule, monitoring setup | 🟡 Medium |
| **Phase 5: Evaluation** | Ongoing | A/B testing, performance monitoring, periodic retraining | 🟢 Low |

---

## Success Metrics

### Model Performance
- **MAE (P50)**: <5% of mean TP (e.g., <25 points for TP=500)
- **Coverage (P10-P90)**: 75-85% (target 80%)
- **Latency**: <1 second for forecast generation

### Business Value
- **Forecast Horizon**: Full market day (up to 375 minutes)
- **Update Frequency**: Every 30-60 seconds
- **Reliability**: >95% uptime, <1% fallback rate

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Insufficient data | High | Start with 30-day minimum, extend to 60+ days |
| Overfitting | High | Cross-validation, regularization, ensemble |
| Regime shifts | High | Adaptive weighting, regime detection, rapid retraining |
| Latency spikes | Medium | Caching, ANN indexing, timeout fallback |
| Model staleness | Medium | Automated weekly retraining |

---

## Quick Decision Tree

**Q: Should we use this architecture?**  
✅ **Yes** — if you need accurate TP forecasts with uncertainty quantification

**Q: When to use each component?**

- **Baseline only**: Sanity checks, structural analysis
- **Kalman**: Preprocessing for noisy TP series
- **Retrieval only**: Stable regimes, abundant historical data
- **GBRT + Retrieval**: **Recommended** — best accuracy and robustness
- **Composite**: Sparse data or frequent regime shifts
- **Conformal**: **Always** — post-process any forecast for calibrated bands

**Q: Do we have the data?**  
✅ **Yes** — Minute-level TP, IV, Greeks, volume, OI (excellent quality)

**Q: Can we meet latency requirements?**  
✅ **Yes** — GBRT inference <200ms, retrieval (cached) <500ms, total <1s

**Q: Is it production-ready?**  
⚠️ **Almost** — Need to implement GBRT integration (Phases 1-3, ~3-4 weeks)

---

## Related Documentation

### Core ML Documents
- **[Full Analysis](ML_ARM_REFACTORING_ANALYSIS.md)** — Comprehensive 10-section analysis (this summary's source)
- **[ML Overview](ML_OVERVIEW.md)** — Path forecasting paradigm introduction
- **[ML Path Forecast Audit](ML_PATH_FORECAST_AUDIT.md)** — Phase A/B/C/D refactoring history
- **[ML Path Forecast Strategy](ML_PATH_FORECAST_STRATEGY.md)** — Long-term roadmap (transformer, etc.)

### Specialized Guides
- **[ANN Recommendations](ml/ANN_RECOMMENDATIONS.md)** — Approximate nearest neighbor indexing
- **[Calibration K Guide](ml/CALIBRATION_K_GUIDE.md)** — K-neighbor tuning for retrieval
- **[ML Arm User Guide](ml/ML_ARM_USER_GUIDE.md)** — End-user operations
- **[ML Improvement Plan](ml/ML_IMPROVEMENT_PLAN.md)** — Feature enhancement tracking

### Architecture
- **[Pipeline Design](architecture/PIPELINE_DESIGN.md)** — Data flow and orchestration
- **[Collector System Guide](COLLECTOR_SYSTEM_GUIDE.md)** — Data collection architecture

---

## Conclusion

**Can we forecast TP with current methods?**  
✅ **Yes, with optimization.**

**Recommended next step:**  
🔴 **Implement GBRT integration** (Phases 1-3, 3-4 weeks)

**Expected outcome:**  
✅ Production-ready ensemble forecaster with <5% MAE, 80% coverage, <1s latency

**Long-term vision:**  
Transform from retrieval-only to hybrid ensemble, then explore transformer integration (Phase 1-2 roadmap) as computational resources and data volume grow.

---

**Document Prepared By**: ML Arm Refactoring Analysis Team  
**Last Updated**: 2025-11-16  
**Version**: 1.0
