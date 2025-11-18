## Adaptive TTL Impact Summary (Quick Sample)

Test Config:
- Horizon: 60m
- Indices: NIFTY, BANKNIFTY
- QPS Target: 10
- Duration per run: 15s (150 requests total)
- Window size param: recent_window_size=60

Environment:
- Adaptive TTL ON: G6_FORECAST_CACHE_ADAPTIVE_TTL=1 (min=10s max=60s base TTL=30)
- Adaptive TTL OFF: G6_FORECAST_CACHE_ADAPTIVE_TTL=0 (fixed TTL=30s)

### Aggregate Metrics
| Mode | P50 Latency (ms) | P95 Latency (ms) | Error Rate | Actual QPS |
|------|------------------|------------------|------------|------------|
| Adaptive ON | 6.56 | 8.38 | 0.00% | 10.00 |
| Adaptive OFF | 6.65 | 8.46 | 0.00% | 10.00 |

### Per-Index Cache Hit Ratio
| Index | Adaptive ON | Adaptive OFF |
|-------|-------------|--------------|
| NIFTY | 66.67% | 66.67% |
| BANKNIFTY | 65.33% | 66.67% |

### Observations
- Latency differences within noise for this very short sample (≤ ~0.1ms delta in P50, ~0.08ms delta P95).
- Cache hit ratios roughly equal; adaptive mode did not yet shift TTL distribution noticeably at this scale.
- No errors recorded; normalized error p90 = 0.0 (expected for mock calculation).

### Next Steps
1. Extend duration to ≥5 minutes to allow differentiated TTL expirations and observe change in hit ratio.
2. Add logging of per-entry TTL in cache stats endpoint to confirm adaptive assignments.
3. Introduce higher volatility simulated inputs (vary `avg_iv`) to force larger TTL compression/expansion swings.
4. Capture eviction counter deltas (not visible in quick test) and correlate with adaptive regime.

### Suggested Longer Test Command
```powershell
$env:G6_FORECAST_CACHE_ADAPTIVE_TTL='1'
python scripts/ml/load_test_ensemble_multi.py --indices NIFTY,BANKNIFTY --qps 25 --duration 300 --horizon 60 --base http://127.0.0.1:9500 --output reports/loadtest/ttl_on_long.json

$env:G6_FORECAST_CACHE_ADAPTIVE_TTL='0'
python scripts/ml/load_test_ensemble_multi.py --indices NIFTY,BANKNIFTY --qps 25 --duration 300 --horizon 60 --base http://127.0.0.1:9500 --output reports/loadtest/ttl_off_long.json
```

### Acceptance Criteria (Draft)
- Adaptive mode should achieve ≥5% improvement in hit ratio or ≥5% reduction in P95 latency under elevated volatility without >10% increase in eviction rate.
