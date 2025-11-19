# ML Drift Monitoring Guide - Phase 10

> WARNING: This Phase 10 implementation currently uses synthetic placeholder distributions (random normal samples) in `compute_feature_distributions`. Integrate real feature extraction (CSV or DB pipeline) before relying on alerts for production decisions. Health gauges `g6_drift_last_eval_ms` and `g6_drift_alert_count` were added for operational monitoring.

**Status:** Production Ready  
**Version:** 1.0  
**Last Updated:** 2025-11-18

---

## Overview

The drift monitoring system tracks feature distribution changes over time to detect when ML model inputs deviate significantly from their baseline behavior. This is critical for maintaining prediction quality and identifying when model retraining or recalibration may be needed.

### Key Features

- **Real-time monitoring**: Continuous evaluation of feature distributions
- **Multiple drift metrics**: PSI, KS test, mean/variance tracking
- **Automatic baseline management**: Creates and persists baselines
- **Prometheus integration**: Exposes metrics for alerting and visualization
- **Grafana dashboards**: Pre-built panels for drift visualization
- **REST API**: Query drift metrics programmatically

---

## Drift Metrics Explained

### 1. Population Stability Index (PSI)

**What it measures:** Overall distribution shift between baseline and recent data

**Calculation:**
```
PSI = Σ (recent_pct - baseline_pct) × ln(recent_pct / baseline_pct)
```

**Interpretation:**
- **PSI < 0.1**: No significant change (stable)
- **0.1 ≤ PSI < 0.25**: Minor shift (monitor)
- **PSI ≥ 0.25**: Major shift (investigate/retrain)
- **PSI > 0.4**: Critical shift (immediate action)

**Use case:** Overall health check for feature stability

### 2. Kolmogorov-Smirnov (KS) Test

**What it measures:** Statistical significance of distribution differences

**Output:**
- **ks_statistic**: Maximum difference between CDFs (0-1)
- **ks_pvalue**: Probability distributions are the same

**Interpretation:**
- **p-value > 0.05**: No significant difference
- **0.01 < p-value ≤ 0.05**: Weak evidence of drift
- **p-value ≤ 0.01**: Strong evidence of drift (alert threshold)
- **p-value < 0.001**: Very strong evidence (critical)

**Use case:** Statistical validation of perceived drift

### 3. Mean Delta (Z-score normalized)

**What it measures:** Change in feature average, scaled by baseline variability

**Calculation:**
```
mean_delta = (recent_mean - baseline_mean) / baseline_std
```

**Interpretation:**
- **|Z| < 2**: Normal variation
- **2 ≤ |Z| < 3**: Noteworthy shift
- **|Z| ≥ 3**: Significant shift (alert threshold)
- **|Z| > 5**: Extreme shift (investigate)

**Use case:** Detect shifts in central tendency

### 4. Variance Delta (Ratio)

**What it measures:** Change in feature variability

**Calculation:**
```
var_delta = (recent_var - baseline_var) / baseline_var
```

**Interpretation:**
- **|var_delta| < 0.2**: Stable volatility
- **|var_delta| ≥ 0.5**: Significant volatility change
- **var_delta > 1.0**: Doubled volatility (increased noise)
- **var_delta < -0.5**: Halved volatility (compression)

**Use case:** Detect changes in feature noisiness

---

## Thresholds and Alert Conditions

### Default Thresholds

| Metric | Warning | Critical | Tunable Via |
|--------|---------|----------|-------------|
| PSI | 0.25 | 0.40 | `G6_DRIFT_PSI_THRESHOLD` |
| KS p-value | 0.01 | 0.001 | `G6_DRIFT_KS_PVALUE_THRESHOLD` |
| Mean Z-score | ±3.0 | ±5.0 | `G6_DRIFT_MEAN_ZSCORE_THRESHOLD` |
| Variance delta | ±0.5 | ±1.0 | (not configurable) |

### Alert Types

1. **Sustained Drift**: Feature in alert state 3 out of last 5 evaluations
2. **Broad Drift**: More than 5 features in alert state simultaneously
3. **Critical Drift**: PSI > 0.4 OR KS p-value < 0.001

---

## Configuration

### Environment Variables

| Variable | Purpose | Default | Notes |
|----------|---------|---------|-------|
| `G6_DRIFT_ENABLE` | Enable drift monitoring | `0` | Set to `1` to activate |
| `G6_DRIFT_BASELINE_DAYS` | Baseline window (days) | `30` | Last N calendar days |
| `G6_DRIFT_RECENT_ROWS` | Recent window (rows) | `300` | Intraday sample size |
| `G6_DRIFT_EVAL_INTERVAL_SEC` | Evaluation frequency | `300` | 5 minutes |
| `G6_DRIFT_INDICES` | Indices to monitor | `NIFTY,BANKNIFTY,SENSEX` | Comma-separated |
| `G6_DRIFT_PSI_THRESHOLD` | PSI alert threshold | `0.25` | Major shift level |
| `G6_DRIFT_KS_PVALUE_THRESHOLD` | KS p-value threshold | `0.01` | Significance level |
| `G6_DRIFT_MEAN_ZSCORE_THRESHOLD` | Mean delta Z-score | `3.0` | Standard deviations |

### Example Configuration

```bash
# Enable drift monitoring
export G6_DRIFT_ENABLE=1

# Use 60-day baseline with 500 recent samples
export G6_DRIFT_BASELINE_DAYS=60
export G6_DRIFT_RECENT_ROWS=500

# Evaluate every 10 minutes
export G6_DRIFT_EVAL_INTERVAL_SEC=600

# Monitor NIFTY, BANKNIFTY and SENSEX
export G6_DRIFT_INDICES="NIFTY,BANKNIFTY,SENSEX"

# Use stricter thresholds
export G6_DRIFT_PSI_THRESHOLD=0.20
export G6_DRIFT_MEAN_ZSCORE_THRESHOLD=2.5
```

---

## API Usage

### Endpoint: GET /api/ml/ensemble/drift

Query drift metrics for an index.

**Parameters:**
- `index` (required): Index name (e.g., "NIFTY")
- `features` (optional): Comma-separated feature names (empty = all)
- `full` (optional): Include full bin-level details (0=summary, 1=full)

**Example Request:**
```bash
curl "http://localhost:9500/api/ml/ensemble/drift?index=NIFTY&full=1"
```

**Example Response:**
```json
{
  "index": "NIFTY",
  "baseline_days": 30,
  "recent_rows": 300,
  "generated_at": 1700000000000,
  "features": {
    "tp_residual_lag1": {
      "psi": 0.18,
      "ks_pvalue": 0.045,
      "mean_delta": -0.012,
      "var_delta": 0.031,
      "alert": false,
      "bins": [
        {"bin": 0, "baseline": 0.10, "recent": 0.12, "psi": 0.003},
        ...
      ]
    },
    "index_return_1min": {
      "psi": 0.32,
      "ks_pvalue": 0.001,
      "mean_delta": 0.15,
      "var_delta": 0.42,
      "alert": true
    }
  },
  "summary": {
    "total_features": 25,
    "alerts": 2
  }
}
```

---

## Prometheus Metrics

### Exposed Gauges

All metrics include labels: `{feature="...", index="..."}`

| Metric | Description | Range |
|--------|-------------|-------|
| `g6_feature_psi` | Population Stability Index | 0+ (unbounded) |
| `g6_feature_ks_pvalue` | KS test p-value | 0.0 - 1.0 |
| `g6_feature_mean_delta` | Mean delta (absolute) | ℝ (unbounded) |
| `g6_feature_var_delta` | Variance delta ratio | ℝ (unbounded) |
| `g6_feature_drift_flag` | Binary alert flag | 0 or 1 |
| `g6_drift_last_eval_ms` | Epoch ms of last drift evaluation | epoch ms |
| `g6_drift_alert_count` | Current alerting feature count per index | 0+ |

### Example PromQL Queries

**Active drift alerts:**
```promql
sum(g6_feature_drift_flag{index="NIFTY"})
```

**Features with PSI > 0.25:**
```promql
count(g6_feature_psi{index="NIFTY"} > 0.25)
```

**Average PSI per index:**
```promql
avg by (index) (g6_feature_psi)
```

**Drift alert rate (last hour):**
```promql
sum(rate(g6_feature_drift_flag[1h])) by (feature)
```

---

## Operational Playbook

### Scenario 1: Single Feature Drift Alert

**Symptoms:**
- One feature shows PSI > 0.25 or KS p-value < 0.01
- Other features stable

**Investigation Steps:**
1. Check drift details:
   ```bash
   curl "http://localhost:9500/api/ml/ensemble/drift?index=NIFTY&features=<feature_name>&full=1"
   ```

2. Review bin-level distribution:
   - Are changes concentrated in specific bins?
   - Is the shift gradual or sudden?

3. Check data quality:
   - Any gaps or anomalies in recent data?
   - Collection pipeline healthy?

4. Review recent market events:
   - Significant news or events?
   - Structural changes (e.g., expiry rollover)?

**Actions:**
- **If transient**: Monitor for resolution (may self-correct)
- **If persistent**: Consider baseline recalibration
- **If data issue**: Fix collection, invalidate affected period

### Scenario 2: Broad Drift (Multiple Features)

**Symptoms:**
- 5+ features in alert state
- May span multiple indices

**Investigation Steps:**
1. Get full drift report:
   ```bash
   curl "http://localhost:9500/api/ml/ensemble/drift?index=NIFTY" | jq '.summary'
   ```

2. Identify common patterns:
   - Are affected features related (e.g., all lag features)?
   - Is drift consistent across indices?

3. Check system health:
   - Data collection pipeline errors?
   - Resource constraints?
   - Recent code/config changes?

**Actions:**
- **If regime change**: Plan model retraining with new baseline
- **If data issue**: Investigate and fix root cause
- **If expected**: Update baseline and document change

### Scenario 3: Critical Drift (PSI > 0.4)

**Symptoms:**
- PSI exceeds 0.4 for one or more features
- Immediate alert triggered

**Investigation Steps:**
1. **URGENT**: Check data integrity
   - Raw data source accessible?
   - Recent pipeline changes?

2. Assess model impact:
   - Are predictions obviously degraded?
   - Has MAE/coverage changed?

3. Compare distributions visually:
   - Plot baseline vs recent histograms
   - Look for bimodality or clipping

**Actions:**
- **If data corruption**: Halt affected predictions, fix data
- **If legitimate shift**: Emergency retraining or fallback to baseline-only
- **If false alarm**: Adjust thresholds or baseline window

### Scenario 4: Sustained Drift (3 of 5 evaluations)

**Symptoms:**
- Feature repeatedly alerts over 25+ minutes
- Not resolving naturally

**Investigation Steps:**
1. Check alert history:
   ```promql
   sum_over_time(g6_feature_drift_flag{feature="..."}[30m])
   ```

2. Review trend:
   - Is drift worsening or stabilizing?
   - Does it correlate with market sessions?

**Actions:**
- **If stabilizing**: Update baseline to new regime
- **If worsening**: Prioritize investigation and retraining
- **If cyclical**: May be time-of-day effect (consider feature engineering)

---

## Tuning Guidelines

### Adjusting Thresholds

**When to loosen thresholds (reduce sensitivity):**
- High false positive rate (>10%)
- Frequent alerts for known benign changes
- High-volatility markets with legitimate variability

**Suggested adjustments:**
- Increase `G6_DRIFT_PSI_THRESHOLD` to 0.30
- Decrease `G6_DRIFT_KS_PVALUE_THRESHOLD` to 0.005
- Increase `G6_DRIFT_MEAN_ZSCORE_THRESHOLD` to 4.0

**When to tighten thresholds (increase sensitivity):**
- Missing real drift events
- Model quality degrading before alerts
- High stability environment with rare changes

**Suggested adjustments:**
- Decrease `G6_DRIFT_PSI_THRESHOLD` to 0.20
- Increase `G6_DRIFT_KS_PVALUE_THRESHOLD` to 0.05
- Decrease `G6_DRIFT_MEAN_ZSCORE_THRESHOLD` to 2.5

### Adjusting Baseline Window

**Longer baseline (e.g., 60 days):**
- **Pros**: More stable, smooths short-term fluctuations
- **Cons**: Slower to adapt to genuine regime changes
- **Use when**: Markets are stable, data is consistent

**Shorter baseline (e.g., 14 days):**
- **Pros**: More responsive to recent changes
- **Cons**: May be noisy, sensitive to short-term events
- **Use when**: Markets are volatile, rapid adaptation needed

### Adjusting Recent Window

**Larger recent window (e.g., 500 rows):**
- **Pros**: More statistically robust comparisons
- **Cons**: Less responsive to very recent changes
- **Use when**: High sample rate, want stability

**Smaller recent window (e.g., 100 rows):**
- **Pros**: More responsive to current conditions
- **Cons**: May be noisy, less statistical power
- **Use when**: Low sample rate or real-time sensitivity critical

---

## Baseline Management

### Automatic Baseline Creation

On first evaluation for an index, the system automatically:
1. Computes feature distributions from last N days
2. Persists to `metrics/drift_baselines/<index>.json`
3. Uses this baseline for all subsequent comparisons

### Manual Baseline Update

To recalibrate baseline after a regime change:

```bash
# Delete existing baseline
rm metrics/drift_baselines/NIFTY.json

# Next evaluation will create new baseline
# Or trigger via API (if implemented):
# curl -X POST "http://localhost:9500/api/ml/ensemble/drift/baseline?index=NIFTY&recalibrate=true"
```

### Baseline Validation

Check baseline health:
```bash
# View baseline metadata
cat metrics/drift_baselines/NIFTY.json | jq '{saved_at, window_start, window_end, features: .features | keys}'
```

**Red flags:**
- Baseline older than 90 days
- Very few samples (< 1000 data points)
- Features with extreme distributions (all zeros, no variance)

---

## Integration with Model Retraining

### Retraining Triggers

Consider retraining when:
1. **Broad drift persists**: 5+ features alerted for 24+ hours
2. **Critical drift observed**: Any feature PSI > 0.4
3. **Sustained drift**: Same feature(s) alert repeatedly over days
4. **Model performance degraded**: MAE increased >10% or coverage dropped <70%

### Retraining Workflow

```bash
# 1. Capture current state
curl "http://localhost:9500/api/ml/ensemble/drift?index=NIFTY" > pre_retrain_drift.json

# 2. Trigger retraining (use your retraining script)
python scripts/ml/automated_retraining.py --index NIFTY --days 60

# 3. Update baseline to reflect new training data
rm metrics/drift_baselines/NIFTY.json

# 4. Validate new model
python scripts/ml/validate_model.py --index NIFTY

# 5. Monitor post-deployment
# Check that drift alerts clear within 1-2 evaluation cycles
```

---

## Troubleshooting

### Problem: No metrics in Prometheus

**Diagnosis:**
```bash
# Check if drift enabled
echo $G6_DRIFT_ENABLE

# Check metrics endpoint
curl http://localhost:9500/metrics | grep g6_feature
```

**Solutions:**
- Ensure `G6_DRIFT_ENABLE=1`
- Verify drift evaluator thread started (check logs)
- Confirm Prometheus scraping dashboard endpoint

### Problem: All features showing drift

**Diagnosis:**
```bash
curl "http://localhost:9500/api/ml/ensemble/drift?index=NIFTY" | jq '.summary'
```

**Likely causes:**
- **Baseline too old**: Update baseline
- **Data pipeline issue**: Check data quality
- **Wrong recent window**: Adjust `G6_DRIFT_RECENT_ROWS`

### Problem: Drift alerts never trigger

**Diagnosis:**
- Check current metrics values:
  ```promql
  g6_feature_psi{index="NIFTY"}
  ```

**Likely causes:**
- **Thresholds too loose**: Tighten thresholds
- **Recent = baseline**: System may be comparing similar data
- **Low variability**: Features may be too stable for current thresholds

### Problem: High false positive rate

**Diagnosis:**
- Review alert history and compare with actual model performance

**Solutions:**
1. **Loosen thresholds** (see Tuning Guidelines)
2. **Increase baseline window** for more stability
3. **Filter out noisy features** (exclude from monitoring)
4. **Add hysteresis**: Require multiple consecutive alerts

---

## Best Practices

1. **Start conservative**: Use default thresholds, tune based on experience
2. **Monitor weekly**: Review drift patterns and adjust baselines quarterly
3. **Document changes**: Log all threshold adjustments and baseline updates
4. **Combine signals**: Don't act on PSI alone—check KS test and mean delta
5. **Validate post-retraining**: Confirm drift clears after model updates
6. **Integrate with CI/CD**: Include drift checks in model deployment pipeline
7. **Alert fatigue prevention**: Use sustained/broad alert rules, not per-evaluation
8. **Maintain baseline currency**: Update baselines after confirmed regime changes

---

## Related Documentation

- **ML_ARM_NEXT_STEPS.md**: Overall ML roadmap and Phase 10 objectives
- **ENSEMBLE_API.md**: Forecast API documentation
- **PRODUCTION_DEPLOYMENT_GUIDE.md**: Deployment procedures
- **ML_IMPROVEMENT_PLAN.md**: Performance optimization strategies

---

## Appendix: Statistical Formulas

### PSI Calculation (Detailed)

Given baseline and recent distributions binned into `n` bins:

```
For each bin i:
  baseline_pct[i] = count_baseline[i] / total_baseline
  recent_pct[i] = count_recent[i] / total_recent
  
  psi[i] = (recent_pct[i] - baseline_pct[i]) × ln(recent_pct[i] / baseline_pct[i])

PSI = Σ psi[i] for i = 1 to n
```

**Binning strategy:** Use baseline quantiles (deciles by default) as bin edges.

### KS Test (Kolmogorov-Smirnov)

The KS test compares empirical cumulative distribution functions (ECDFs):

```
D = max |ECDF_baseline(x) - ECDF_recent(x)| for all x

p-value = P(D_observed | H0: distributions are same)
```

**Interpretation:** Low p-value rejects null hypothesis → distributions differ.

### Z-Score Normalization

For mean delta:

```
Z = (μ_recent - μ_baseline) / σ_baseline

where:
  μ_recent = mean of recent samples
  μ_baseline = mean of baseline samples
  σ_baseline = standard deviation of baseline samples
```

**Interpretation:** |Z| > 3 means shift is >3 standard deviations from baseline mean.

---

**Document Version:** 1.0  
**Maintained By:** ML Engineering Team  
**Feedback:** ml-team@example.com
