## Adaptive TTL Long-Run Comparison (5m @ 25 QPS)

Test Parameters:
- Duration: 300s (5 minutes)
- Target QPS: 25 (≈7500 requests per mode)
- Indices: NIFTY, BANKNIFTY (50/50 round-robin)
- Horizon: 60 minutes
- Base TTL (fixed): 30s; Adaptive bounds: 10s–60s

### Aggregate Metrics
| Mode | Requests | P50 Latency (ms) | P95 Latency (ms) | Error Rate | Cache Hit Ratio (combined)* |
|------|----------|------------------|------------------|------------|-----------------------------|
| Adaptive ON | 7500 | 5.70 | 7.35 | 0.00% | 86.64% |
| Adaptive OFF | 7501 | 5.94 | 7.57 | 0.00% | 86.64% |

*Combined hit ratio derived from per-index identical ratios (no divergence observed).

### Per-Index Metrics (Selected)
| Index | Mode | Requests | P50 Lat (ms) | P95 Lat (ms) | Cache Hit Ratio |
|-------|------|----------|-------------|-------------|-----------------|
| NIFTY | Adaptive ON | 3750 | 5.69 | 7.35 | 86.64% |
| NIFTY | Adaptive OFF | 3751 | 5.95 | 7.56 | 86.64% |
| BANKNIFTY | Adaptive ON | 3750 | 5.71 | 7.35 | 86.64% |
| BANKNIFTY | Adaptive OFF | 3750 | 5.94 | 7.58 | 86.64% |

### Observations
1. Latency: Adaptive TTL shows modest improvement (~4.0% lower P50 and ~3.0% lower P95 vs fixed TTL) in this sample.
2. Cache Hit Ratio: Essentially identical (≈86.64%) across modes; suggests TTL not yet a limiting factor under steady homogeneous request pattern.
3. Error Rate: 0%; stability unaffected by adaptive strategy.
4. Normalized Error P90: 0.0 due to mock calculation in load test harness (expected).
5. Convergence: Identical hit ratio implies majority of requests fall within TTL window even for fixed 30s; adaptive extension/compression not stressed.

### Interpretation
The slight latency reduction without change in hit ratio implies incidental variance rather than clear adaptive benefit. To surface TTL differentiation, a higher diversity workload (varying horizons / indices / quantile sets) or volatility-driven TTL scaling is needed.

### Recommended Follow-Ups
| Priority | Action | Goal |
|----------|--------|------|
| High | Introduce horizon diversity (15,30,60,120) | Increase cache key churn to stress TTL adaptation |
| High | Simulate volatility variation (vary `avg_iv`) | Force adaptive TTL to shorten/extend durations |
| Medium | Log per-entry effective TTL in cache stats | Provide evidence of dynamic TTL assignment |
| Medium | Track eviction counter deltas per mode | Confirm adaptive reduces thrashing under churn |
| Low | Extend duration to 15m with volatility spikes | Observe long-run stability drift |

### Draft Success Criteria (Refined)
- Adaptive TTL yields ≥5% improvement in P95 latency OR ≥5% improvement in hit ratio under heterogeneous request patterns.
- No increase >10% in eviction rate versus fixed TTL baseline.
- Latency variance (stddev) not inflated (>10%) by adaptive strategy.

### Next Experiment Command Sketch
```powershell
# Mixed horizons & simulated volatility
$env:G6_FORECAST_CACHE_ADAPTIVE_TTL='1'
python scripts/ml/load_test_ensemble_multi.py --indices NIFTY,BANKNIFTY --qps 40 --duration 600 --horizon 60 --base http://127.0.0.1:9500 --output reports/loadtest/ttl_on_mixed.json

$env:G6_FORECAST_CACHE_ADAPTIVE_TTL='0'
python scripts/ml/load_test_ensemble_multi.py --indices NIFTY,BANKNIFTY --qps 40 --duration 600 --horizon 60 --base http://127.0.0.1:9500 --output reports/loadtest/ttl_off_mixed.json
```

Augment harness to randomize horizon and inject `avg_iv` variation for next run to properly evaluate adaptive effectiveness.

### Conclusion
Initial 5-minute high-QPS test indicates neutral cache efficiency and minor latency gain. More diverse workloads required to validate adaptive TTL value proposition.
