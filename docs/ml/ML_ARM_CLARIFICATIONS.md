# ML ARM Implementation - Clarifications and FAQ
**Date:** 2025-11-16  
**Status:** Official Clarifications

---

## Q1: Do we use OTM option data or just ATM data to forecast TP?

### **Answer: Currently ATM-Only**

**Current Implementation:**
- The system forecasts **ATM Total Premium (TP)** = ATM_CE_Premium + ATM_PE_Premium
- Training data includes **only ATM strike** options (CE and PE at the money)
- OTM strikes are **not included** in current TP forecasting models

**Evidence from Code:**
```python
# src/analytics/ml/baseline.py
# Baseline formula uses ATM straddle concept
baseline_tp = k * underlying * iv_proxy * sqrt(T)

# src/path_forecast/common.py
# TP extraction looks for ATM-specific keys:
ce_keys = ("ce","ce_ltp","atm_ce","call_ltp","call","atm_call","ce_price","atm_ce_ltp")
pe_keys = ("pe","pe_ltp","atm_pe","put_ltp","put","atm_put","pe_price","atm_pe_ltp")
```

**Why ATM-Only:**
1. **Simplicity**: ATM straddle is a standard market indicator
2. **Liquidity**: ATM options have highest liquidity and tightest spreads
3. **Baseline Formula**: Structural model (Bachelier-like) naturally fits ATM premium
4. **Computational Cost**: Including all OTM strikes would explode feature space

**Future Enhancement (Optional):**
- Could extend to "TP Curve" forecasting across strikes
- Would require multi-output models or strike-parametric models
- See: `DEFERRED_ENHANCEMENTS.md` for "Strike Curve Forecasting"

### **Recommendation:**
✅ **Keep ATM-only for Phase 1-4**  
⏭️ **Consider OTM extension in Phase 5** (Evaluation & Improvement) if business needs it

---

## Q2: Is INDIAVIX part of the training dataset?

### **Answer: NO - Not Currently Used**

**Current Status:**
```bash
# Search results:
grep -r "INDIAVIX" src/     # No matches
grep -r "india_vix" src/    # No matches
```

**INDIAVIX is NOT:**
- ❌ Collected by current data pipeline
- ❌ Stored in CSV snapshots
- ❌ Used in baseline or retrieval models
- ❌ Part of proposed GBRT feature set

**Why Not Included:**
1. **Implicit via Option IVs**: INDIAVIX represents market-wide IV, which is already captured via:
   - Individual option IVs (CE_IV, PE_IV)
   - Average IV used in baseline formula
   - Rolling IV statistics in regime features

2. **Redundancy**: Adding INDIAVIX would be **highly correlated** with Avg IV features
   - Correlation coefficient likely > 0.9
   - GBRT would automatically downweight one of them
   - No value added, just noise

3. **Data Availability**: Would require separate API call to fetch INDIAVIX time series

**Should We Add It?**

**NO - for these reasons:**

| Reason | Explanation |
|--------|-------------|
| **Collinearity** | INDIAVIX ~= Avg(CE_IV, PE_IV), adds no new information |
| **GBRT Handles It** | Model learns from individual IVs; doesn't need market aggregate |
| **Engineering Cost** | Requires new data collection + storage pipeline |
| **Minimal Benefit** | Unlikely to improve MAE by >1% |

**If Business Insists:**
- Add as a **regime feature** (INDIAVIX percentile)
- Use as **auxiliary monitoring metric** (not training input)
- Validate via ablation study (train with/without INDIAVIX)

### **Recommendation:**
✅ **Skip INDIAVIX in Phase 1-4**  
⏭️ **Add only if ablation study shows >2% MAE improvement**

---

## Q3: How to handle correlation between input features?

### **Answer: GBRT Handles Correlation Automatically**

**Three Approaches:**

### **Approach 1: Do Nothing (Recommended) ✅**

**Why:** Gradient Boosting (GBRT/LightGBM/XGBoost) is **robust to multicollinearity**

**How it works:**
- Trees split on **one feature at a time**
- If two features are correlated, model picks the **more informative one** first
- Later splits refine using the other feature if needed
- Built-in **feature importance** naturally downweights redundant features

**Example:**
```
Features: [avg_iv, vix, ce_iv, pe_iv]  # All correlated!
GBRT learns: avg_iv most important → use it for first splits
             ce_iv - pe_iv (spread) → secondary splits (captures skew)
             vix → mostly ignored (redundant with avg_iv)
```

**No Manual Intervention Needed:**
- Don't create "correlation features" manually
- Don't remove correlated features
- Let the model **auto-select** via feature importance

---

### **Approach 2: Add Interaction/Ratio Features (Optional)**

**When to use:** If domain knowledge suggests **non-linear relationships**

**Examples:**
```python
# Good interactions to add:
tp_residual_lag1 * avg_iv           # Momentum × Volatility
index_return_5min / avg_iv          # Price change normalized by vol
(ce_iv - pe_iv) / avg_iv            # IV skew ratio
time_to_expiry * avg_iv²            # Vol-weighted time decay

# Bad interactions (redundant):
avg_iv * ce_iv                       # Already captured by avg_iv
index_price * index_price            # GBRT learns non-linearity
```

**Implementation:**
```python
# In feature_engineering.py
features['iv_momentum'] = features['res_lag1'] * features['avg_iv']
features['iv_skew_ratio'] = (features['ce_iv'] - features['pe_iv']) / features['avg_iv']
```

**Test via Cross-Validation:**
- Train model **with and without** interaction features
- Keep only if validation MAE improves by >1%

---

### **Approach 3: Feature Selection (Advanced)**

**When to use:** If you have **>50 features** and want to reduce overfitting

**Methods:**
1. **Feature Importance Filtering:**
   ```python
   # After initial training:
   importances = model.feature_importances_
   top_features = features[importances > threshold]  # e.g., top 20
   ```

2. **Recursive Feature Elimination (RFE):**
   ```python
   from sklearn.feature_selection import RFE
   selector = RFE(model, n_features_to_select=20, step=5)
   X_selected = selector.fit_transform(X_train, y_train)
   ```

3. **Correlation-Based Pruning:**
   ```python
   # Remove one feature from each highly correlated pair (|corr| > 0.95)
   corr_matrix = X_train.corr().abs()
   upper = corr_matrix.where(np.triu(np.ones_like(corr_matrix), k=1).astype(bool))
   to_drop = [column for column in upper.columns if any(upper[column] > 0.95)]
   ```

**Trade-offs:**
- ✅ Reduces training time
- ✅ May improve generalization (less overfitting)
- ❌ Loses potentially useful information
- ❌ Adds complexity to pipeline

---

### **Recommended Strategy for ML ARM:**

**Phase 1-2 (Initial Training):**
1. ✅ Include all 24 proposed features
2. ✅ Train GBRT without manual feature selection
3. ✅ Analyze `feature_importances_` after training
4. ✅ Document top 15 features

**Phase 3 (Ensemble Integration):**
5. ✅ Keep all features (GBRT handles correlation)
6. ✅ Add 2-3 domain-driven interactions if needed (e.g., IV skew)

**Phase 5 (Evaluation & Improvement):**
7. ⏭️ Experiment with feature selection if overfitting detected
8. ⏭️ A/B test reduced feature set vs. full feature set

---

## Q4: Index Price Relationship to ATM Premium

### **Correction: Relationship is Complex**

**Original Statement (WRONG):**
> "Index Price: Structural dependency (higher index → higher ATM premium)"

**Corrected Understanding:**

**The relationship between index price and ATM premium is NOT linear:**

1. **For ATM Straddle (CE + PE):**
   - When index moves **up**: CE premium ↑, PE premium ↓
   - When index moves **down**: CE premium ↓, PE premium ↑
   - **Net effect on TP:** Depends on **Gamma, Vega, and IV response**

2. **What Actually Matters:**
   - **Absolute Index Price Level:** Used in baseline formula as scaling factor
     - `baseline_tp = k * underlying * iv * sqrt(T)`
     - Higher index → proportionally higher baseline (all else equal)
   
   - **Index Price Change (Returns):** Captures momentum/directional moves
     - `index_return_1min`, `index_return_5min` (features in model)
     - These affect **residual** (deviation from baseline), not baseline itself

3. **Greeks Impact:**
   - **Gamma**: Convexity effect (TP increases with |price move|)
   - **Vega**: IV change with price move (usually IV ↑ when price ↓ sharply)
   - **Correlation**: Index moves often coincide with IV changes

**Correct Feature Design:**
```python
# Baseline uses absolute level:
baseline_tp = k * index_price * avg_iv * sqrt(T)

# Features capture dynamics:
features['index_return_1min'] = (index_price_t - index_price_t-1) / index_price_t-1
features['index_return_5min'] = (index_price_t - index_price_t-5) / index_price_t-5
features['index_vol_5min'] = rolling_std(index_returns, window=5)

# GBRT learns: how TP residual responds to these movements
residual = actual_tp - baseline_tp
residual ~ f(index_return_1min, index_return_5min, avg_iv, ...)
```

**Updated Documentation:**
- ✅ Corrected in `ML_ARM_REFACTORING_ANALYSIS.md` (line 542)
- ✅ Clarified in this document

---

## Summary of Key Points

| Question | Answer | Action Needed |
|----------|--------|---------------|
| **OTM data in training?** | ❌ No, ATM-only currently | ✅ Documented - keep ATM-only for Phase 1-4 |
| **INDIAVIX in features?** | ❌ No, not used (redundant with IVs) | ✅ Skip - already captured via option IVs |
| **Correlation handling?** | ✅ GBRT auto-handles via feature importance | ✅ No manual intervention needed |
| **Index→TP relationship?** | ⚠️ Complex, not simply "higher→higher" | ✅ Documentation corrected |

---

## Feature Engineering Specification (Updated)

### **Confirmed Features (24 total):**

#### **Lag Features (12):**
- ✅ `res_lag_1`, `res_lag_2`, `res_lag_5`, `res_lag_10`, `res_lag_30`, `res_lag_60`
- ✅ `res_rolling_mean_5min`, `res_rolling_mean_15min`, `res_rolling_mean_30min`
- ✅ `res_rolling_std_5min`, `res_rolling_std_15min`, `res_rolling_std_30min`

#### **Market Features (8):**
- ✅ `index_return_1min`, `index_return_5min`
- ✅ `avg_iv`, `avg_iv_change_1min`
- ✅ `minutes_to_expiry_norm`
- ✅ `time_of_day_sin`, `time_of_day_cos`
- ✅ `weekday`

#### **Regime Features (4):**
- ✅ `iv_percentile` (0-1 scale, rolling 60min)
- ✅ `index_vol_percentile` (rolling std percentile)
- ✅ `volume_ratio` (current vol / daily avg vol)
- ✅ `oi_change_rate`

### **NOT Included:**
- ❌ INDIAVIX (redundant)
- ❌ OTM strike data (out of scope)
- ❌ Manual correlation features (GBRT handles)

---

## References

**Related Documents:**
- `ML_ARM_IMPLEMENTATION_ROADMAP.md` - Implementation plan
- `ML_ARM_REFACTORING_ANALYSIS.md` - Analysis (corrected)
- `ML_ROADMAP_TP_FORECAST.md` - Original ML roadmap
- `DEFERRED_ENHANCEMENTS.md` - Future OTM/curve forecasting

**Code References:**
- `src/analytics/ml/baseline.py` - Baseline TP formula
- `src/path_forecast/common.py` - TP extraction logic
- `src/analytics/ml/quantile.py` - GBRT framework

---

**Contact:** ML Engineering Team  
**Last Updated:** 2025-11-16
