# Ensemble Path Forecaster Guide

## Overview

The Ensemble Path Forecaster is a sophisticated system that combines multiple forecasting approaches to predict ATM Total Premium (TP) with quantified uncertainty. It implements Phase 3 of the ML ARM Implementation Roadmap.

### Key Features

1. **Multi-Model Fusion**: Combines baseline structural model, GBRT quantile regression, and K-NN retrieval
2. **Adaptive Weighting**: Dynamically adjusts component weights based on confidence scores
3. **Conformal Calibration**: Provides well-calibrated uncertainty bands
4. **Robust Fallbacks**: Gracefully degrades when components fail
5. **Production Ready**: Includes monitoring, logging, and error handling

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                   EnsembleForecaster                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Baseline   │  │     GBRT     │  │  Retrieval   │     │
│  │   TP Model   │  │   Quantile   │  │   K-NN       │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            │                                 │
│                    ┌───────▼────────┐                       │
│                    │   Confidence   │                       │
│                    │   Computation  │                       │
│                    └───────┬────────┘                       │
│                            │                                 │
│                    ┌───────▼────────┐                       │
│                    │    Adaptive    │                       │
│                    │   Weighting    │                       │
│                    └───────┬────────┘                       │
│                            │                                 │
│                    ┌───────▼────────┐                       │
│                    │   Forecast     │                       │
│                    │  Combination   │                       │
│                    └───────┬────────┘                       │
│                            │                                 │
│                    ┌───────▼────────┐                       │
│                    │   Conformal    │                       │
│                    │  Calibration   │                       │
│                    └───────┬────────┘                       │
│                            │                                 │
│                    ┌───────▼────────┐                       │
│                    │  Final P10/    │                       │
│                    │  P50/P90       │                       │
│                    └────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

### Forecast Pipeline

The ensemble forecaster follows this 7-step pipeline:

1. **Baseline Computation**: `TP_baseline = k * underlying * iv * sqrt(T)`
2. **GBRT Residual Forecast**: Predict residuals using trained GBRT models
3. **Retrieval Forecast**: Get forecasts from historical pattern matching
4. **Confidence Scoring**: Compute confidence based on candidates and regime
5. **Adaptive Weighting**: Calculate component weights based on confidence
6. **Forecast Combination**: Blend residuals and add baseline
7. **Conformal Calibration**: Apply uncertainty quantification

---

## Configuration

### Configuration File Structure

```json
{
  "ensemble_type": "hybrid_adaptive",
  "index": "NIFTY",
  
  "components": {
    "baseline": {
      "enabled": true,
      "k_coefficient": 1.0
    },
    "gbrt": {
      "enabled": true,
      "model_path": "models/nifty_gbrt_quantile/model.joblib",
      "feature_config": {...}
    },
    "retrieval": {
      "enabled": true,
      "data_root": "data/historical",
      "k": 20,
      "window": 60,
      ...
    },
    "conformal": {
      "enabled": true,
      "target_coverage": 0.8,
      "window": 600
    }
  },
  
  "weighting": {
    "strategy": "confidence_adaptive",
    "confidence_threshold": 0.7,
    "weights_high_confidence": {"gbrt": 0.8, "retrieval": 0.2},
    "weights_low_confidence": {"gbrt": 0.5, "retrieval": 0.5}
  }
}
```

### Component Configuration

#### Baseline

- `enabled`: Enable/disable baseline component
- `k_coefficient`: Scaling coefficient (default: 1.0)

#### GBRT

- `enabled`: Enable/disable GBRT component
- `model_path`: Path to trained GBRT model (.joblib file)
- `feature_config`: Feature extraction configuration

#### Retrieval

- `enabled`: Enable/disable retrieval component
- `data_root`: Root directory for historical data
- `k`: Number of nearest neighbors (default: 20)
- `window`: Lookback window in minutes (default: 60)
- `min_days`: Minimum historical days required
- `distance_metric`: Distance metric (l2, cosine, recent_l2)
- `use_ann`: Enable approximate nearest neighbor search

#### Conformal

- `enabled`: Enable/disable conformal calibration
- `target_coverage`: Target coverage probability (default: 0.8)
- `window`: Rolling window size (default: 600)
- `min_radius`: Minimum band radius

### Weighting Strategy

The ensemble supports three weighting strategies:

1. **confidence_adaptive** (recommended): Adjusts weights based on confidence score
2. **static**: Always uses high confidence weights
3. **dynamic**: Custom dynamic weighting (extensible)

#### Confidence Thresholds

- `confidence_threshold`: Boundary between high/low confidence (default: 0.7)
- `min_candidates_threshold`: Minimum retrieval candidates for high confidence (default: 5)

#### Weight Configuration

**High Confidence** (confidence ≥ 0.7):
- GBRT: 0.8 (80%)
- Retrieval: 0.2 (20%)
- *Rationale*: Trust ML model more when sufficient data available

**Low Confidence** (confidence < 0.7):
- GBRT: 0.5 (50%)
- Retrieval: 0.5 (50%)
- *Rationale*: Balance models when uncertainty is high

---

## Usage

### Basic Usage

```python
from pathlib import Path
from src.path_forecast.ensemble import EnsembleForecaster, EnsembleConfig

# Load configuration
cfg = EnsembleConfig(
    baseline_enabled=True,
    gbrt_enabled=True,
    retrieval_enabled=True,
    gbrt_model_path=Path("models/nifty_gbrt_quantile/model.joblib"),
    retrieval_root=Path("data/historical"),
)

# Initialize forecaster
forecaster = EnsembleForecaster(cfg)

# Prepare input
recent_window = [[100.0], [101.0], ...]  # Recent TP observations
context = {
    "index": "NIFTY",
    "now_ms": 1700000000000,
    "underlying": 19500.0,
    "avg_iv": 0.15,
    "minutes_to_expiry": 300.0,
}

# Generate forecast
times, quantiles = forecaster.forecast_path(
    recent_window,
    context=context,
    quantiles=[0.1, 0.5, 0.9],
    horizon_minutes=60,
)

# Extract results
p50_forecast = quantiles[0.5]  # Median forecast
p10_forecast = quantiles[0.1]  # Lower band
p90_forecast = quantiles[0.9]  # Upper band

# Check metadata
meta = forecaster.last_meta
confidence = meta["confidence"]
weight_gbrt = meta["weight_gbrt"]
```

### Command-Line Usage

Run the ensemble forecaster as a service:

```bash
# Single test run
python scripts/ml/run_ensemble_forecaster.py \
    --config configs/ml/nifty_ensemble_config.json \
    --index NIFTY \
    --test

# Continuous forecasting
python scripts/ml/run_ensemble_forecaster.py \
    --config configs/ml/nifty_ensemble_config.json \
    --index NIFTY \
    --output data/ml/live_predictions/nifty_ensemble.csv \
    --interval 60

# Daemon mode
python scripts/ml/run_ensemble_forecaster.py \
    --config configs/ml/nifty_ensemble_config.json \
    --index NIFTY \
    --daemon
```

**Options**:
- `--config`: Path to configuration JSON file (required)
- `--index`: Index name (NIFTY, BANKNIFTY, etc.)
- `--output`: Output CSV file path
- `--interval`: Update interval in seconds (default: 60)
- `--test`: Run single iteration for testing
- `--daemon`: Run continuously in background
- `--max-iterations`: Maximum number of iterations

---

## Output Format

### Forecast Structure

The `forecast_path` method returns:

```python
(times, quantiles)
```

Where:
- `times`: List of timestamps in milliseconds
- `quantiles`: Dict mapping quantile → sequence of values

Example:
```python
times = [1700000060000, 1700000120000, ...]  # Future timestamps
quantiles = {
    0.1: [95.0, 96.0, ...],   # P10 forecast
    0.5: [100.0, 101.0, ...], # P50 forecast (median)
    0.9: [105.0, 106.0, ...], # P90 forecast
}
```

### CSV Output

When using `--output`, predictions are written to CSV:

```csv
timestamp,index,horizon_min,p10,p50,p90,confidence,weight_gbrt,weight_retrieval
2025-11-16 10:00:00,NIFTY,1,95.5,100.0,104.5,0.850,0.800,0.200
2025-11-16 10:01:00,NIFTY,1,95.8,100.2,104.8,0.860,0.800,0.200
```

### Metadata

After each forecast, metadata is available in `forecaster.last_meta`:

```python
{
    "index": "NIFTY",
    "horizon": 60,
    "quantiles": [0.1, 0.5, 0.9],
    "baseline_tp": 100.5,
    "baseline_enabled": True,
    "gbrt_enabled": True,
    "gbrt_available": True,
    "retrieval_enabled": True,
    "retrieval_available": True,
    "retrieval_candidates": 15,
    "retrieval_k": 20,
    "confidence": 0.85,
    "weight_gbrt": 0.8,
    "weight_retrieval": 0.2,
    "total_ms": 45,  # If profiling enabled
}
```

---

## Confidence Computation

### Confidence Score

Confidence is computed based on:

1. **Retrieval Candidates**: More historical matches → higher confidence
2. **Market Regime**: (Future) Stable regime → higher confidence
3. **Model Recency**: (Future) Fresh model → higher confidence

### Current Formula

```python
candidates = retrieval_candidates
threshold = min_candidates_threshold

if candidates >= 2 * threshold:
    confidence = 0.9
elif candidates >= threshold:
    confidence = 0.7 + 0.2 * (candidates - threshold) / threshold
elif candidates > 0:
    confidence = 0.5 + 0.2 * candidates / threshold
else:
    confidence = 0.5  # Neutral
```

### Confidence Levels

| Confidence | Interpretation | Weight Strategy |
|------------|----------------|-----------------|
| ≥ 0.9 | Very High | 80% GBRT / 20% Retrieval |
| 0.7 - 0.9 | High | 80% GBRT / 20% Retrieval |
| 0.5 - 0.7 | Medium | Interpolated |
| < 0.5 | Low | 50% GBRT / 50% Retrieval |

---

## Adaptive Weighting

### Weight Computation

Given confidence `c` and threshold `t`:

```python
if c >= t:
    # High confidence
    w_gbrt = weights_high_conf_gbrt
    w_retrieval = weights_high_conf_retrieval
else:
    # Low confidence - interpolate
    alpha = c / t
    w_gbrt = alpha * weights_high_conf_gbrt + (1 - alpha) * weights_low_conf_gbrt
    w_retrieval = alpha * weights_high_conf_retrieval + (1 - alpha) * weights_low_conf_retrieval

# Normalize
total = w_gbrt + w_retrieval
w_gbrt /= total
w_retrieval /= total
```

### Example Weight Transitions

| Confidence | GBRT Weight | Retrieval Weight |
|------------|-------------|------------------|
| 0.9 | 0.80 | 0.20 |
| 0.7 | 0.80 | 0.20 |
| 0.6 | 0.73 | 0.27 |
| 0.5 | 0.65 | 0.35 |
| 0.4 | 0.58 | 0.42 |
| 0.3 | 0.50 | 0.50 |

---

## Fallback Mechanisms

The ensemble includes multiple fallback layers:

### Component Fallbacks

1. **GBRT Disabled/Unavailable**: Use retrieval only
2. **Retrieval Disabled/Unavailable**: Use GBRT only
3. **Both Unavailable**: Use baseline only

### Forecast Fallbacks

1. **Primary Pipeline Fails**: Use flat forecast with bands
2. **No Recent Data**: Use baseline TP
3. **Configuration Error**: Return safe default

### Error Handling

```python
try:
    # Generate ensemble forecast
    times, quantiles = forecaster.forecast_path(...)
except Exception as e:
    # Log error and use fallback
    times, quantiles = forecaster._fallback_forecast(...)
```

---

## Monitoring and Diagnostics

### Enable Profiling

Set `enable_profiling: true` in configuration to track:

- Component latencies
- Memory usage
- Cache hit rates
- Detailed timing breakdown

### Metadata Inspection

```python
meta = forecaster.last_meta

# Check component availability
if not meta.get("gbrt_available"):
    print("GBRT component unavailable")

# Check confidence
if meta["confidence"] < 0.5:
    print("Low confidence - consider retraining")

# Check timings (if profiling enabled)
if "total_ms" in meta:
    print(f"Forecast took {meta['total_ms']}ms")
```

### Logging

The ensemble uses structured logging:

```python
import logging

# Set log level
logging.getLogger("path_forecast.ensemble").setLevel(logging.DEBUG)

# Logs include:
# - Component initialization
# - Forecast generation
# - Errors and warnings
# - Performance metrics
```

---

## Performance Considerations

### Latency

Typical latency breakdown:

- Baseline: < 1ms
- GBRT: 5-20ms (depends on features)
- Retrieval: 10-50ms (depends on k and window)
- Conformal: < 1ms
- **Total**: 20-80ms typical

### Memory

- GBRT model: 10-50 MB
- Retrieval cache: 50-200 MB
- Conformal window: < 1 MB
- **Total**: 100-300 MB typical

### Optimization Tips

1. **Enable ANN for Retrieval**: Use `use_ann: true` for large datasets
2. **Reduce k**: Lower k = faster retrieval
3. **Shorter Window**: Smaller lookback = less computation
4. **Cache Models**: Keep models in memory

---

## Troubleshooting

### Common Issues

#### 1. GBRT Model Not Found

**Error**: `GBRT model path not found: models/...`

**Solution**: Train GBRT model first:
```bash
python scripts/ml/train_gbrt_quantile.py \
    --config configs/ml/nifty_tp_forecast_gbrt_quantile.json
```

#### 2. Insufficient Historical Candidates

**Error**: `insufficient historical candidates for retrieval`

**Solution**: 
- Reduce `min_days` in configuration
- Increase `max_days_scan`
- Check data availability

#### 3. Low Confidence Warnings

**Warning**: `Low confidence - balancing models`

**Solution**:
- Normal when few historical matches
- Consider retraining if persistent
- Check data quality

#### 4. High Latency

**Issue**: Forecasts take > 1 second

**Solution**:
- Enable profiling to identify bottleneck
- Reduce retrieval k or window
- Enable ANN for retrieval
- Check system resources

---

## Testing

### Unit Tests

Run ensemble tests:

```bash
pytest tests/ml/test_ensemble_forecaster.py -v
```

Test coverage includes:
- Configuration validation
- Baseline computation
- Confidence scoring
- Weight computation
- Forecast combination
- Fallback mechanisms
- End-to-end integration

### Integration Tests

Test with real data:

```python
from pathlib import Path
from src.path_forecast.ensemble import EnsembleForecaster, EnsembleConfig

# Setup
cfg = EnsembleConfig(
    retrieval_root=Path("data/historical"),
    gbrt_model_path=Path("models/nifty_gbrt_quantile/model.joblib"),
)
forecaster = EnsembleForecaster(cfg)

# Load real data
import pandas as pd
df = pd.read_csv("data/historical/NIFTY/this_week/0/2025-11-15.csv")

# Generate forecast
recent_window = [[v] for v in df["tp"].tail(60)]
context = {
    "index": "NIFTY",
    "now_ms": int(df["timestamp"].iloc[-1]),
    "underlying": df["underlying"].iloc[-1],
    "avg_iv": df["avg_iv"].iloc[-1],
    "minutes_to_expiry": 300.0,
}

times, quantiles = forecaster.forecast_path(recent_window, context=context)
```

---

## Best Practices

### Model Training

1. **Regular Retraining**: Retrain GBRT models weekly or biweekly
2. **Validation**: Always validate models before deployment
3. **Feature Engineering**: Ensure feature consistency across train/inference
4. **Hyperparameter Tuning**: Tune on recent data

### Configuration

1. **Start Conservative**: Begin with balanced weights (0.5/0.5)
2. **Gradual Optimization**: Incrementally adjust based on performance
3. **Monitor Confidence**: Track confidence distributions
4. **Version Control**: Keep configs in git

### Deployment

1. **Canary Rollout**: Test on subset of traffic first
2. **Monitor Metrics**: Track MAE, coverage, latency
3. **Alerting**: Set up alerts for anomalies
4. **Fallbacks**: Always have fallback mechanisms

### Monitoring

1. **Coverage**: Ensure 75-85% empirical coverage
2. **MAE**: Monitor prediction accuracy
3. **Confidence**: Track confidence score distribution
4. **Latency**: Keep P95 latency < 100ms
5. **Errors**: Alert on error rate > 1%

---

## References

- [ML ARM Implementation Roadmap](ML_ARM_IMPLEMENTATION_ROADMAP.md)
- [ML ARM Refactoring Analysis](ML_ARM_REFACTORING_ANALYSIS.md)
- [Feature Engineering Guide](FEATURE_ENGINEERING_GUIDE.md)
- [GBRT Training Guide](MODEL_TRAINING_RUNBOOK.md)

---

## Support

For issues or questions:
- Open issue in GitHub repository
- Contact ML Engineering Team
- Refer to troubleshooting section above
