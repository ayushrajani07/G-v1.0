## Mixed Horizon & Volatility Adaptive TTL Comparison (90s @ 50 QPS)

Configuration:
- Indices: NIFTY, BANKNIFTY
- Horizons randomized: 15, 30, 60, 120
- Quantile sets randomized: [0.1,0.5,0.9] and [0.05,0.25,0.5,0.75,0.95]
- avg_iv randomized in [0.15, 0.45]
- recent_window_size=60
- Duration: 90s (~4500 requests)
- Forecast cache reported size: 500 (capacity reached) in both runs

### Results
| Mode | Requests | P50 Lat (ms) | P95 Lat (ms) | Error Rate | Cache Hit Ratio | Unique Key Fingerprints |
|------|----------|--------------|--------------|------------|-----------------|-------------------------|
| Adaptive TTL ON | 4500 | 6.32 | 7.29 | 0.00% | 0.00% | 8 |
| Adaptive TTL OFF | 4500 | 7.15 | 8.58 | 0.00% | 0.02% | 8 |

### Observations
1. Latency improvement: Adaptive reduces P50 by ~11.6% and P95 by ~15.0% vs fixed TTL under high key churn (two quantile sets * four horizons * two indices).  
2. Hit ratio near zero for both due to aggressive key diversity and short TTL exposure—each unique combination rarely reused within test window.  
3. Forecast cache size at capacity (500) for both modes: indicates frequent insertions (evictions likely; eviction counters should be inspected separately).  
4. Unique key fingerprint count (8) reflects collapsed representation (index + horizon + recent_count + quantile name set); real key diversity higher (different avg_iv values not included in fingerprint).  
5. Adaptive advantage here derives from shorter effective TTL on volatile combinations reducing recomputation overhead? (Needs validation—current latency gain may reflect incidental CPU cache locality or warm path effects).  
6. Very low hit ratio suggests optimization focus should shift to key normalization or selective parameter bucketing (e.g., quantile set consolidation or horizon grouping) alongside adaptive TTL.  

### Recommended Follow-Ups
| Priority | Action | Rationale |
|----------|--------|-----------|
| High | Expose eviction counters & per-entry TTL in `/cache/stats` | Distinguish adaptive TTL mechanism from general cache pressure |
| High | Add key normalization strategy (bucket avg_iv into discrete bands) | Increase potential reuse & hit ratio |
| Medium | Add horizon sampling bias (weighted towards 30/60) | Mirror production distribution for realistic benefit assessment |
| Medium | Record TTL per inserted entry (debug flag) | Empirical proof of adaptive adjustments |
| Medium | Separate latency for cache hits vs misses | Quantify potential gain if hit ratio improved |
| Low | Include retrieval + model component timing breakdown | Identify dominant latency components under churn |

### Draft Enhancement Criteria
- After normalization, mixed test should reach ≥10% hit ratio with ≤5% latency regression vs current adaptive result.  
- Adaptive TTL should lower eviction rate ≥10% under identical churn compared to fixed TTL (once eviction metric added).  
- Latency P95 improvement ≥10% maintained after normalization phase.  

### Suggested Next Commands (after instrumentation additions)
```powershell
# Extended run with normalization experiment (example bucketed avg_iv)
$env:G6_FORECAST_CACHE_ADAPTIVE_TTL='1'
python scripts/ml/load_test_ensemble_mixed.py --indices NIFTY,BANKNIFTY --horizons 15,30,60,120 --qps 50 --duration 180 --avg-iv-range 0.15,0.45 --quantile-sets "0.1,0.5,0.9" --output reports/loadtest/mixed_ttl_on_norm.json

$env:G6_FORECAST_CACHE_ADAPTIVE_TTL='0'
python scripts/ml/load_test_ensemble_mixed.py --indices NIFTY,BANKNIFTY --horizons 15,30,60,120 --qps 50 --duration 180 --avg-iv-range 0.15,0.45 --quantile-sets "0.1,0.5,0.9" --output reports/loadtest/mixed_ttl_off_norm.json
```

### Conclusion
Adaptive TTL shows latency benefit under extreme churn but cache effectiveness collapses for both modes at high diversity. Improving reuse (key normalization) + deeper metrics needed before finalizing adaptive TTL adoption criteria.
