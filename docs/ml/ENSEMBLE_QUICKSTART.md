# Ensemble Forecaster Quick Start

## 5-Minute Setup

### 1. Install Dependencies

```bash
pip install numpy pandas scikit-learn joblib
```

### 2. Basic Usage

```python
from pathlib import Path
from src.path_forecast.ensemble import EnsembleForecaster, EnsembleConfig

# Simple configuration
cfg = EnsembleConfig(
    baseline_enabled=True,
    gbrt_enabled=False,  # Enable after training model
    retrieval_enabled=False,  # Enable with historical data
)

# Initialize
forecaster = EnsembleForecaster(cfg)

# Generate forecast
recent_window = [[100.0 + i*0.5] for i in range(60)]
context = {
    "index": "NIFTY",
    "now_ms": 1700000000000,
    "underlying": 19500.0,
    "avg_iv": 0.15,
    "minutes_to_expiry": 300.0,
}

times, quantiles = forecaster.forecast_path(
    recent_window,
    context=context,
    quantiles=[0.1, 0.5, 0.9],
    horizon_minutes=60,
)

print(f"P50 forecast: {quantiles[0.5][0]:.2f}")
```

### 3. Command Line

```bash
# Test run
python scripts/ml/run_ensemble_forecaster.py \
    --config configs/ml/nifty_ensemble_config.json \
    --index NIFTY \
    --test

# Production
python scripts/ml/run_ensemble_forecaster.py \
    --config configs/ml/nifty_ensemble_config.json \
    --index NIFTY \
    --output predictions.csv \
    --interval 60
```

## Configuration Templates

### Baseline Only (Fastest)

```json
{
  "components": {
    "baseline": {"enabled": true},
    "gbrt": {"enabled": false},
    "retrieval": {"enabled": false},
    "conformal": {"enabled": false}
  }
}
```

### GBRT + Baseline (Recommended)

```json
{
  "components": {
    "baseline": {"enabled": true},
    "gbrt": {
      "enabled": true,
      "model_path": "models/nifty_gbrt_quantile/model.joblib"
    },
    "retrieval": {"enabled": false},
    "conformal": {"enabled": true}
  }
}
```

### Full Ensemble (Production)

```json
{
  "components": {
    "baseline": {"enabled": true},
    "gbrt": {
      "enabled": true,
      "model_path": "models/nifty_gbrt_quantile/model.joblib"
    },
    "retrieval": {
      "enabled": true,
      "data_root": "data/historical",
      "k": 20
    },
    "conformal": {"enabled": true}
  },
  "weighting": {
    "strategy": "confidence_adaptive",
    "confidence_threshold": 0.7
  }
}
```

## Common Tasks

### Check Forecast Quality

```python
# After forecast
meta = forecaster.last_meta

print(f"Confidence: {meta['confidence']:.3f}")
print(f"GBRT weight: {meta['weight_gbrt']:.2f}")
print(f"Retrieval candidates: {meta.get('retrieval_candidates', 0)}")
```

### Update Conformal Band

```python
# After observing actual value
forecaster.update_conformal(predicted=100.0, actual=102.5)
```

### Enable Profiling

```python
cfg = EnsembleConfig(enable_profiling=True)
forecaster = EnsembleForecaster(cfg)

# After forecast
print(f"Total time: {forecaster.last_meta['total_ms']}ms")
```

## Troubleshooting

| Issue | Quick Fix |
|-------|-----------|
| "GBRT model not found" | Set `gbrt_enabled: false` or train model |
| "Insufficient candidates" | Reduce `min_days` or add historical data |
| Low confidence | Normal with limited data |
| High latency | Reduce `k` or enable ANN |

## Next Steps

1. Read [Ensemble Guide](ENSEMBLE_GUIDE.md) for details
2. Train GBRT models (if needed)
3. Collect historical data for retrieval
4. Set up monitoring and alerts
5. Deploy to production

## Key Metrics

Monitor these metrics:

- **Coverage**: Should be 75-85%
- **MAE**: < 5% of mean TP
- **Latency**: < 100ms P95
- **Confidence**: Track distribution

## Resources

- Full guide: [ENSEMBLE_GUIDE.md](ENSEMBLE_GUIDE.md)
- Training: [MODEL_TRAINING_RUNBOOK.md](MODEL_TRAINING_RUNBOOK.md)
- Roadmap: [ML_ARM_IMPLEMENTATION_ROADMAP.md](ML_ARM_IMPLEMENTATION_ROADMAP.md)
