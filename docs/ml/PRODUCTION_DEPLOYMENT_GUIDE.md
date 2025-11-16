# ML Ensemble Production Deployment Guide

**Version:** 1.0  
**Date:** 2025-11-16  
**Status:** Phase 4 Implementation Complete

---

## Overview

This guide provides step-by-step instructions for deploying the ML Ensemble forecasting system to production. The deployment includes API services, metrics exporters, monitoring dashboards, and automated retraining.

**Components:**
- ML Ensemble API Server
- Prometheus Metrics Exporter
- Grafana Dashboard
- Alert Rules
- Automated Retraining Pipeline

---

## Prerequisites

### System Requirements
- Python 3.8+
- 4GB+ RAM (8GB+ recommended)
- 10GB+ disk space for models and data
- Network access for API endpoints

### Dependencies
```bash
pip install -r requirements.txt
pip install flask prometheus-client
```

### Data Requirements
- Historical TP data (minimum 30 days, recommended 60 days)
- Trained GBRT models in `models/{index}_gbrt_quantile/`
- Configuration files in `configs/ml/`

---

## Deployment Steps

### Step 1: Verify Configuration

1. **Check ensemble configurations:**
```bash
ls -la configs/ml/
# Should see:
# - nifty_ensemble_config.json
# - banknifty_ensemble_config.json
# - nifty_tp_forecast_gbrt_quantile.json
# - banknifty_tp_forecast_gbrt_quantile.json
```

2. **Verify model files:**
```bash
ls -la models/nifty_gbrt_quantile/
# Should see:
# - model_q10.joblib
# - model_q50.joblib
# - model_q90.joblib
# - training_report.json
```

3. **Test configuration loading:**
```bash
python -c "from src.web.api.ml_ensemble import create_app; app = create_app(); print('✓ Configuration valid')"
```

### Step 2: Deploy ML Ensemble API

1. **Start API server:**
```bash
# Development mode (with debug)
python src/web/api/ml_ensemble.py --host 0.0.0.0 --port 9210 --debug

# Production mode
nohup python src/web/api/ml_ensemble.py --host 0.0.0.0 --port 9210 > logs/ml_api.log 2>&1 &
```

2. **Verify API is running:**
```bash
# Health check
curl http://localhost:9210/health

# Test forecast endpoint
curl "http://localhost:9210/api/ml/ensemble/forecast?index=NIFTY&horizon=60"

# Test diagnostics
curl "http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY"
```

3. **Check logs:**
```bash
tail -f logs/ml_api.log
```

### Step 3: Deploy Metrics Exporter

1. **Start Prometheus exporter:**
```bash
# NIFTY exporter (port 9325)
nohup python scripts/ml/ml_ensemble_metrics_exporter.py \
    --index NIFTY \
    --config configs/ml/nifty_ensemble_config.json \
    --port 9325 \
    --interval 60 > logs/ml_metrics_nifty.log 2>&1 &

# BANKNIFTY exporter (port 9326)
nohup python scripts/ml/ml_ensemble_metrics_exporter.py \
    --index BANKNIFTY \
    --config configs/ml/banknifty_ensemble_config.json \
    --port 9326 \
    --interval 60 > logs/ml_metrics_banknifty.log 2>&1 &
```

2. **Verify metrics endpoint:**
```bash
curl http://localhost:9325/metrics | grep g6_ml_ensemble
```

3. **Check Prometheus scrape config:**
```yaml
# Add to prometheus.yml
scrape_configs:
  - job_name: 'ml_ensemble_nifty'
    static_configs:
      - targets: ['localhost:9325']
        labels:
          service: 'ml_ensemble'
          index: 'NIFTY'
  
  - job_name: 'ml_ensemble_banknifty'
    static_configs:
      - targets: ['localhost:9326']
        labels:
          service: 'ml_ensemble'
          index: 'BANKNIFTY'
```

### Step 4: Configure Prometheus Alerts

1. **Add alert rules to Prometheus:**
```bash
# Copy alert rules
cp prometheus_rules_ml_ensemble.yml /etc/prometheus/rules/

# Update prometheus.yml
# Add to rule_files:
rule_files:
  - "rules/prometheus_rules_ml_ensemble.yml"
```

2. **Reload Prometheus configuration:**
```bash
# Send reload signal
kill -HUP $(pgrep prometheus)

# Or restart Prometheus
systemctl restart prometheus
```

3. **Verify rules loaded:**
```bash
# Check Prometheus UI
# Navigate to: http://localhost:9090/rules
# Look for ml_ensemble_* rules
```

### Step 5: Deploy Grafana Dashboard

1. **Import dashboard:**
```bash
# Option 1: Via Grafana UI
# - Go to Dashboards → Import
# - Upload dashboards_modular/ml_ensemble_monitoring.json
# - Select Prometheus datasource
# - Click Import

# Option 2: Via API
curl -X POST \
  http://localhost:3000/api/dashboards/db \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_API_KEY' \
  -d @dashboards_modular/ml_ensemble_monitoring.json
```

2. **Access dashboard:**
```
URL: http://localhost:3000/d/ml_ensemble_v1/ml-ensemble-monitoring
```

3. **Verify panels display data:**
- Forecast quantiles (P10/P50/P90)
- Confidence score
- Coverage rate
- Component weights
- Latency metrics

### Step 6: Setup Automated Retraining

1. **Create cron job for weekly retraining:**
```bash
# Edit crontab
crontab -e

# Add entry (Sunday at 2 AM)
0 2 * * 0 /usr/bin/python3 /path/to/scripts/ml/automated_retraining.py --index NIFTY --days 60 >> /path/to/logs/retraining.log 2>&1
0 3 * * 0 /usr/bin/python3 /path/to/scripts/ml/automated_retraining.py --index BANKNIFTY --days 60 >> /path/to/logs/retraining.log 2>&1
```

2. **Test retraining manually:**
```bash
python scripts/ml/automated_retraining.py \
    --index NIFTY \
    --days 60 \
    --improvement-threshold 0.05 \
    --debug
```

3. **Verify retraining logs:**
```bash
tail -f logs/retraining.log
```

---

## Operational Procedures

### Starting Services

**Start all services:**
```bash
# 1. Start API server
./scripts/ml/start_ml_api.sh

# 2. Start metrics exporters
./scripts/ml/start_ml_metrics.sh

# 3. Verify services
./scripts/ml/check_ml_status.sh
```

### Stopping Services

**Stop all services:**
```bash
# Stop API server
pkill -f "ml_ensemble.py"

# Stop metrics exporters
pkill -f "ml_ensemble_metrics_exporter.py"
```

### Monitoring Status

**Check service health:**
```bash
# API health
curl http://localhost:9210/health

# Metrics availability
curl http://localhost:9325/metrics | head -20

# Check processes
ps aux | grep "ml_ensemble\|ml_ensemble_metrics"
```

**Monitor logs:**
```bash
# API logs
tail -f logs/ml_api.log

# Metrics logs
tail -f logs/ml_metrics_nifty.log
tail -f logs/ml_metrics_banknifty.log

# Retraining logs
tail -f logs/retraining.log
```

### Viewing Logs

**Log locations:**
- API: `logs/ml_api.log`
- Metrics: `logs/ml_metrics_{index}.log`
- Retraining: `logs/retraining.log`

**View recent errors:**
```bash
grep -i "error" logs/ml_api.log | tail -20
```

---

## Troubleshooting

### API Issues

**Problem:** API not responding
```bash
# Check if process is running
ps aux | grep ml_ensemble.py

# Check port binding
netstat -tuln | grep 9210

# Check logs for errors
tail -50 logs/ml_api.log

# Restart API
pkill -f ml_ensemble.py
python src/web/api/ml_ensemble.py --host 0.0.0.0 --port 9210 &
```

**Problem:** Configuration not found
```bash
# Verify config files exist
ls -la configs/ml/*_ensemble_config.json

# Check config syntax
python -c "import json; print(json.load(open('configs/ml/nifty_ensemble_config.json')))"
```

### Metrics Issues

**Problem:** Metrics not updating
```bash
# Check exporter process
ps aux | grep ml_ensemble_metrics_exporter

# Check Prometheus scrape status
# Visit: http://localhost:9090/targets

# Restart exporter
pkill -f ml_ensemble_metrics_exporter
python scripts/ml/ml_ensemble_metrics_exporter.py --index NIFTY --port 9325 &
```

**Problem:** High latency (>2s)
```bash
# Check system resources
top
df -h

# Profile component latencies
curl "http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY" | jq '.metrics.avg_latency_ms'

# Check retrieval cache
# Increase retrieval window or reduce k value
```

### Coverage Issues

**Problem:** Under-coverage (<75%)
```bash
# Check current coverage
curl http://localhost:9325/metrics | grep g6_ml_ensemble_coverage_actual

# Adjust conformal target in config
# Edit configs/ml/nifty_ensemble_config.json:
# "conformal": {"target_coverage": 0.85}

# Restart services
```

**Problem:** Over-coverage (>90%)
```bash
# Tighten conformal bands
# Edit config: "conformal": {"target_coverage": 0.75}
```

### Model Staleness

**Problem:** Model age > 14 days
```bash
# Check model age
curl http://localhost:9325/metrics | grep g6_ml_ensemble_model_age_days

# Trigger manual retraining
python scripts/ml/automated_retraining.py --index NIFTY --days 60
```

---

## Emergency Fallbacks

### Retrieval-Only Mode

If GBRT models are failing:
```bash
# Edit ensemble config
# Set: "gbrt": {"enabled": false}

# Restart API
pkill -f ml_ensemble.py
python src/web/api/ml_ensemble.py &
```

### Baseline-Only Mode

For maximum stability:
```bash
# Disable ML components
# Set in config:
# "gbrt": {"enabled": false}
# "retrieval": {"enabled": false}

# Restart services
```

---

## Performance Tuning

### Latency Optimization

1. **Increase retrieval cache:**
```json
{
  "retrieval": {
    "window": 120,  // Increase from 60
    "use_ann": true  // Enable approximate nearest neighbors
  }
}
```

2. **Reduce forecast frequency:**
```bash
# Increase interval from 60s to 120s
python scripts/ml/ml_ensemble_metrics_exporter.py --interval 120
```

### Accuracy Improvement

1. **Retrain with more data:**
```bash
python scripts/ml/automated_retraining.py --index NIFTY --days 90
```

2. **Tune hyperparameters:**
```bash
python scripts/ml/tune_gbrt_hyperparams.py --index NIFTY
```

3. **Adjust ensemble weights:**
```json
{
  "weighting": {
    "weights_high_confidence": {
      "gbrt": 0.7,  // Reduce GBRT weight
      "retrieval": 0.3  // Increase retrieval weight
    }
  }
}
```

---

## Monitoring Checklist

**Daily:**
- [ ] Check API health endpoint
- [ ] Verify metrics are updating
- [ ] Review Grafana dashboard
- [ ] Check for active alerts

**Weekly:**
- [ ] Review coverage rates
- [ ] Check MAE trends
- [ ] Verify model age
- [ ] Review retraining logs

**Monthly:**
- [ ] Analyze performance trends
- [ ] Review and update alert thresholds
- [ ] Archive old models
- [ ] Update documentation

---

## Alert Runbooks

### MLEnsembleUnderCoverage

**Severity:** Warning  
**Threshold:** Coverage < 75% for 15m

**Steps:**
1. Check conformal calibration: `curl http://localhost:9325/metrics | grep conformal_radius`
2. Verify data quality: Check for missing/anomalous data
3. Widen bands if needed: Increase `target_coverage` in config
4. Monitor for improvement

### MLEnsembleHighLatency

**Severity:** Warning  
**Threshold:** P95 latency > 2s for 5m

**Steps:**
1. Check system resources: `top`, `df -h`
2. Profile components: Check API diagnostics endpoint
3. Check retrieval cache hit rate
4. Consider reducing GBRT model complexity

### MLEnsembleModelStale

**Severity:** Warning  
**Threshold:** Model age > 14 days

**Steps:**
1. Schedule retraining: Run automated_retraining.py
2. Verify sufficient training data available
3. Monitor retraining job completion
4. Validate new model before promotion

---

## Rollback Procedures

### Rolling Back Model

If new model performs poorly:

```bash
# 1. Find archived model
ls -la models/*_archived_*

# 2. Stop services
pkill -f "ml_ensemble"

# 3. Restore old model
mv models/nifty_gbrt_quantile models/nifty_gbrt_quantile_bad
mv models/nifty_gbrt_quantile_archived_TIMESTAMP models/nifty_gbrt_quantile

# 4. Restart services
python src/web/api/ml_ensemble.py &
python scripts/ml/ml_ensemble_metrics_exporter.py --index NIFTY &
```

### Rolling Back Configuration

```bash
# Restore from backup
cp configs/ml/nifty_ensemble_config.json.backup configs/ml/nifty_ensemble_config.json

# Restart services
pkill -f ml_ensemble
python src/web/api/ml_ensemble.py &
```

---

## Security Considerations

1. **API Access Control:**
   - Deploy behind reverse proxy (nginx/Apache)
   - Enable authentication and rate limiting
   - Use HTTPS in production

2. **Metrics Security:**
   - Restrict Prometheus scrape endpoints to internal network
   - Use firewall rules to limit access

3. **Model Security:**
   - Protect model files with appropriate permissions
   - Encrypt sensitive configuration data
   - Audit model updates

---

## Additional Resources

- **ML ARM Implementation Roadmap:** `docs/ml/ML_ARM_IMPLEMENTATION_ROADMAP.md`
- **Phase 3 Completion:** `PHASE3_COMPLETION_SUMMARY.md`
- **API Documentation:** `src/web/api/ml_ensemble.py` (docstrings)
- **Metrics Documentation:** `prometheus_rules_ml_ensemble.yml` (annotations)

---

## Support

For issues or questions:
1. Check logs first: `logs/ml_*.log`
2. Review this documentation
3. Consult ML Engineering Team
4. Open GitHub issue with full logs

---

**End of Deployment Guide**
