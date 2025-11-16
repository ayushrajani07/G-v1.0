# Phase 4: Production Deployment - Quick Start

**Status:** ✅ Complete  
**Version:** 1.0  
**Date:** 2025-11-16

---

## What is Phase 4?

Phase 4 implements the production deployment infrastructure for the ML Ensemble forecasting system. It provides:

- 🚀 **REST API** for real-time forecasting
- 📊 **Prometheus Metrics** for monitoring
- 📈 **Grafana Dashboard** for visualization
- 🔔 **Alert Rules** for production monitoring
- 🤖 **Automated Retraining** for model maintenance
- 🛠️ **Operational Tools** for service management

---

## Quick Start

### 1. One-Command Deployment

```bash
./scripts/ml/deploy_phase4.sh
```

This interactive script will:
- Check prerequisites
- Create required directories
- Run tests
- Start services (optional)
- Display endpoint URLs

### 2. Manual Step-by-Step

```bash
# Start API server
./scripts/ml/start_ml_api.sh

# Start metrics exporters
./scripts/ml/start_ml_metrics.sh

# Check status
./scripts/ml/check_ml_status.sh
```

### 3. Stop Services

```bash
./scripts/ml/stop_ml_services.sh
```

---

## API Endpoints

### Health Check
```bash
curl http://localhost:9210/health
```

### Get Forecast
```bash
curl "http://localhost:9210/api/ml/ensemble/forecast?index=NIFTY&horizon=60"
```

**Response:**
```json
{
  "index": "NIFTY",
  "horizon": 60,
  "timestamp": "2025-11-16T15:30:00Z",
  "forecast": {
    "p10": 180.5,
    "p50": 195.3,
    "p90": 210.8,
    "band_low": 178.2,
    "band_high": 212.5
  },
  "confidence": 0.75,
  "metadata": {
    "latency_ms": 450,
    "components_used": ["baseline", "gbrt", "retrieval", "conformal"],
    "weights": {"gbrt": 0.7, "retrieval": 0.3}
  }
}
```

### Get Diagnostics
```bash
curl "http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY"
```

### Get Confidence
```bash
curl "http://localhost:9210/api/ml/ensemble/confidence?index=NIFTY"
```

### Trigger Retraining
```bash
curl -X POST http://localhost:9210/api/ml/ensemble/retrain \
  -H "Content-Type: application/json" \
  -d '{"index": "NIFTY", "days": 60, "validate": true}'
```

---

## Metrics

### View Metrics
```bash
# NIFTY metrics
curl http://localhost:9325/metrics

# BANKNIFTY metrics
curl http://localhost:9326/metrics
```

### Key Metrics

**Forecast Metrics:**
- `g6_ml_ensemble_forecast_p10` - P10 quantile forecast
- `g6_ml_ensemble_forecast_p50` - P50 (median) forecast
- `g6_ml_ensemble_forecast_p90` - P90 quantile forecast

**Performance Metrics:**
- `g6_ml_ensemble_confidence` - Confidence score (0-1)
- `g6_ml_ensemble_weight_gbrt` - GBRT component weight
- `g6_ml_ensemble_weight_retrieval` - Retrieval component weight
- `g6_ml_ensemble_latency_seconds` - Forecast latency
- `g6_ml_ensemble_mae_p50` - Mean Absolute Error
- `g6_ml_ensemble_coverage_actual` - Coverage rate

**Health Metrics:**
- `g6_ml_ensemble_model_age_days` - Model age
- `g6_ml_ensemble_forecast_errors_total` - Error count
- `g6_ml_ensemble_forecasts_total` - Forecast count

---

## Grafana Dashboard

### Import Dashboard

1. Open Grafana UI (http://localhost:3000)
2. Go to Dashboards → Import
3. Upload `dashboards_modular/ml_ensemble_monitoring.json`
4. Select Prometheus datasource
5. Click Import

### Dashboard Panels

1. Ensemble Forecast (P10/P50/P90 bands)
2. Confidence Score (gauge)
3. Coverage Rate (gauge)
4. Component Weights (time series)
5. Coverage Percentage (rolling windows)
6. Mean Absolute Error (trends)
7. Forecast Latency (P95/P99)
8. Conformal Band Radius
9. Model Age (gauge)
10. Error Rate
11. Forecast Generation Rate

---

## Alerts

### Configure Prometheus Alerts

1. Copy rules file:
```bash
cp prometheus_rules_ml_ensemble.yml /etc/prometheus/rules/
```

2. Update `prometheus.yml`:
```yaml
rule_files:
  - "rules/prometheus_rules_ml_ensemble.yml"
```

3. Reload Prometheus:
```bash
kill -HUP $(pgrep prometheus)
```

### Alert Examples

- **Coverage < 75%** → Warning
- **Coverage < 70%** → Critical
- **MAE > 15** → Warning
- **Latency > 2s** → Warning
- **Model age > 14 days** → Warning
- **Model age > 30 days** → Critical

---

## Automated Retraining

### Manual Trigger
```bash
python scripts/ml/automated_retraining.py \
    --index NIFTY \
    --days 60 \
    --improvement-threshold 0.05 \
    --debug
```

### Cron Setup
```bash
# Edit crontab
crontab -e

# Add weekly retraining (Sunday at 2 AM)
0 2 * * 0 /usr/bin/python3 /path/to/scripts/ml/automated_retraining.py --index NIFTY --days 60 >> /path/to/logs/retraining.log 2>&1
```

### Retraining Process

1. ✅ Fetch 60 days of data
2. ✅ Generate feature matrix
3. ✅ Train GBRT models (P10, P50, P90)
4. ✅ Validate on held-out data
5. ✅ Compare with production model
6. ✅ Promote if improvement > 5%
7. ✅ Archive old model
8. ✅ Send notification

---

## Troubleshooting

### Services Not Starting

**Check logs:**
```bash
tail -f logs/ml_api.log
tail -f logs/ml_metrics_nifty.log
```

**Check ports:**
```bash
netstat -tuln | grep -E '9210|9325|9326'
```

**Kill stuck processes:**
```bash
pkill -f ml_ensemble
```

### API Errors

**Test configuration:**
```bash
python -c "from src.web.api.ml_ensemble import create_app; app = create_app()"
```

**Check config files:**
```bash
ls -la configs/ml/*.json
python -c "import json; json.load(open('configs/ml/nifty_ensemble_config.json'))"
```

### Metrics Not Updating

**Check exporter:**
```bash
curl http://localhost:9325/metrics | grep g6_ml_ensemble
```

**Verify Prometheus scrape:**
```
http://localhost:9090/targets
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Client/User                        │
└───────────────────┬─────────────────────────────────┘
                    │
         ┌──────────▼──────────┐
         │   ML Ensemble API   │ :9210
         │   (Flask REST)      │
         └──────────┬──────────┘
                    │
         ┌──────────▼──────────────────────────┐
         │    Ensemble Forecaster              │
         │  ┌────────┐ ┌──────┐ ┌──────────┐  │
         │  │Baseline│ │ GBRT │ │Retrieval │  │
         │  └────────┘ └──────┘ └──────────┘  │
         │         Conformal Calibration        │
         └──────────┬──────────────────────────┘
                    │
         ┌──────────▼──────────┐
         │ Metrics Exporter    │ :9325/:9326
         └──────────┬──────────┘
                    │
         ┌──────────▼──────────┐
         │    Prometheus       │ :9090
         └──────────┬──────────┘
                    │
         ┌──────────▼──────────┐
         │     Grafana         │ :3000
         └─────────────────────┘
```

---

## Files Reference

### API & Core
- `src/web/api/ml_ensemble.py` - REST API implementation
- `src/path_forecast/ensemble.py` - Ensemble forecaster

### Monitoring
- `scripts/ml/ml_ensemble_metrics_exporter.py` - Metrics exporter
- `prometheus_rules_ml_ensemble.yml` - Alert rules
- `dashboards_modular/ml_ensemble_monitoring.json` - Dashboard

### Automation
- `scripts/ml/automated_retraining.py` - Retraining pipeline
- `scripts/ml/deploy_phase4.sh` - Deployment script

### Operations
- `scripts/ml/start_ml_api.sh` - Start API
- `scripts/ml/start_ml_metrics.sh` - Start metrics
- `scripts/ml/stop_ml_services.sh` - Stop services
- `scripts/ml/check_ml_status.sh` - Check status

### Documentation
- `docs/ml/PRODUCTION_DEPLOYMENT_GUIDE.md` - Comprehensive guide
- `PHASE4_COMPLETION_SUMMARY.md` - Implementation summary
- `docs/ml/PHASE4_README.md` - This file

### Tests
- `tests/ml/test_ml_api.py` - API unit tests

---

## Support

**Documentation:**
- Full deployment guide: `docs/ml/PRODUCTION_DEPLOYMENT_GUIDE.md`
- Implementation summary: `PHASE4_COMPLETION_SUMMARY.md`
- Roadmap: `docs/ml/ML_ARM_IMPLEMENTATION_ROADMAP.md`

**Logs:**
```bash
# View all logs
tail -f logs/*.log

# View specific service
tail -f logs/ml_api.log
tail -f logs/ml_metrics_nifty.log
```

**Status Check:**
```bash
./scripts/ml/check_ml_status.sh
```

---

## Next Steps

### Immediate
1. ✅ Deploy to staging
2. ✅ Run integration tests
3. ✅ Monitor initial metrics
4. ✅ Validate alerts

### Short-term
1. Collect production metrics
2. Tune alert thresholds
3. Optimize latency
4. Add comprehensive tests

### Long-term
1. **Phase 5:** Evaluation & Continuous Improvement
   - A/B testing
   - Regime-specific evaluation
   - Feature importance tracking
   
2. **Phase 6:** Code Cleanup & Maintenance
   - Remove deprecated code
   - Expand test coverage
   - Improve exception handling

---

## Success Criteria

✅ API responding in < 1s  
✅ Metrics updating every 60s  
✅ Dashboard displaying data  
✅ Alerts configured  
✅ Retraining automated  
✅ Documentation complete  
✅ Tests passing  

---

**Phase 4: Production Deployment - Complete! 🎉**
