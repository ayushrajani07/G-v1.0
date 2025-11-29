# 📘 ML Ops Runbook: Drift & Regime Management

**Version:** 1.0 (Phase 11)
**Owner:** ML Ops Team
**Last Updated:** 2025-11-28

---

## 🚨 Alert Definitions

### 1. Drift Alerts (`g6_drift_alert_count`)
Triggered when forecast performance deviates significantly from the rolling baseline.

| Severity | Condition | Meaning |
|----------|-----------|---------|
| **WARN** | `mae_ratio >= 1.5` OR `norm_ratio >= 1.3` | Model error is 50% higher than recent baseline. |
| **CRITICAL** | `mae_ratio >= 2.0` OR `norm_ratio >= 1.7` | Model error has doubled. Immediate investigation required. |
| **WARN** | `coverage_delta <= -10%` | Uncertainty bands are too narrow (under-covering). |
| **CRITICAL** | `coverage_delta <= -20%` | Severe under-estimation of risk. |

### 2. Regime Breaches (`g6_regime_breach_count`)
Triggered when market conditions shift (Volatility/Trend) causing systematic model failure.

*   **Detection:** Composite score of Coverage Drop + Norm Error Rise.
*   **Impact:** Model assumptions (e.g., mean reversion) may no longer hold.

---

## 🛠️ Triage Process

### Step 1: Verify Data Quality
Before assuming model failure, check the data pipeline.
1.  **Check Dashboard:** Go to `ML Ensemble / Diagnostics`.
2.  **Verify Inputs:** Are `underlying` and `avg_iv` correct?
    *   *Symptom:* `avg_iv` drops to 0 -> Model bands collapse -> False Drift Alert.
    *   *Action:* Restart `scripts/ml/start_ml_api.ps1` to refresh live data connection.

### Step 2: Analyze Drift Context
Use the `/metrics/compare` endpoint or Grafana "Drift Analysis" panel.
*   **Is it sudden?** (Spike in last 1 hour) -> Likely news event or data glitch.
*   **Is it gradual?** (Rising over 2 days) -> Genuine concept drift.

### Step 3: Check Feature Shift
Check `g6_feature_psi` (Population Stability Index).
*   If `PSI > 0.2` for key features (`volatility`, `momentum`), the market regime has changed.
*   *Action:* The model is operating out-of-distribution.

---

## 🔧 Mitigation Actions

### Scenario A: False Positive (Data Glitch)
1.  **Acknowledge:** Note the time window.
2.  **Fix Data:** Restart data collectors.
3.  **Reset State:**
    ```powershell
    # Clear rolling window state to remove bad samples
    Remove-Item data/ml/metrics/rolling_mae_state.json
    Restart-Service ml_api
    ```

### Scenario B: Genuine Drift (Model Decay)
1.  **Short-Term:** Widen Uncertainty Bands.
    *   Edit `configs/ml/{index}_ensemble_config.json`:
        ```json
        "conformal": { "target_coverage": 0.95 }  // Increase from 0.8
        ```
    *   *Effect:* Immediate safety buffer.

2.  **Medium-Term:** Recalibrate Drift Thresholds.
    *   If the "New Normal" has higher volatility, the old baselines are too strict.
    *   Run:
        ```powershell
        python scripts/ml/calibrate_drift_thresholds.py --indices NIFTY --warn-pctl 0.85
        ```
    *   Promote the new manifest:
        ```powershell
        python scripts/ml/govern_drift_thresholds.py --promote
        ```

3.  **Long-Term:** Retrain Models.
    *   Trigger `scripts/ml/automated_retraining.py`.

### Scenario C: Regime Shift (Crisis Mode)
1.  **Enable Fallback:**
    *   Switch `weighting_strategy` to `static` in config.
    *   Force `baseline` (structural) weight to 1.0 if ML is erratic.
2.  **Notify Stakeholders:** Trading logic should reduce position sizing.

---

## 📊 Escalation Policy

| Condition | Response Time | Who to Notify |
|-----------|---------------|---------------|
| **WARN** Drift | 24 Hours | ML Engineer (Next Day) |
| **CRITICAL** Drift | 4 Hours | ML Lead + Trading Desk |
| **Regime Breach** | Immediate | **ALL HANDS** (Stop Trading) |

---

## 📝 Command Reference

**Check Status:**
```powershell
curl http://localhost:9500/api/ml/ensemble/regime/status?index=NIFTY
```

**Force Flush Metrics:**
```powershell
curl -X POST http://localhost:9500/api/ml/ensemble/metrics/flush
```

**View Drift History:**
```powershell
Get-Content data/ml/metrics/drift_history.jsonl -Tail 10
```
