# ANN Path Forecast Recommendations

Date: 2025-11-08

## Executive Summary

Recent large-slice ANN harness runs (extended @ candidates=50 and tuned @ per-mode 20) show that:

- Retrieval mode at 60m window (k=10 or 15) produces the best composite score with zero MAD and positive (raw) effectiveness.
- Retrieval 120m window (k=10 or 15) yields slightly lower speedups but still offers meaningful adjusted effectiveness once pruning improves (effectiveness_score_adjusted up to ~0.13 when pruning ratio < 0.87).
- Auto / Hybrid modes consistently introduce positive MAD (0.15–0.24) that neutralizes speedup/pruning benefits, driving negative adjusted effectiveness.
- Guard trigger rate remained 0.0 across evaluated spans (no fallback activations under current MAD guard threshold logic).

## Recommended Default Config Set

Primary (production):

| Priority | Index Scope | Window (m) | Horizon (m) | k | Mode | Rationale |
|----------|-------------|------------|-------------|---|------|-----------|
| 1 | All (initially NIFTY/BANKNIFTY) | 60 | 60 | 10 | retrieval | Highest stable score; zero MAD; best effectiveness per unit latency. |
| 2 | All | 60 | 60 | 15 | retrieval | Nearly identical performance; keep as a quick A/B or fallback if candidate pressure changes. |
| 3 | All | 120 | 60 | 10 | retrieval | Slightly lower score; provides diversity in historical span; adjusted effectiveness improves when pruning ratio < ~0.88. |
| 4 | All | 120 | 60 | 15 | retrieval | Backup to evaluate sensitivity vs k=10 at larger window. |

Defer / Exclude (by default): auto, hybrid modes for these horizons and windows—negative or zero adjusted effectiveness and higher median absolute deviation.

## Candidate Counts

Adopt per-mode max candidates of 20 for retrieval. Auto/Hybrid not scheduled by default; if reintroduced, start with retrieval=20,auto=20,hybrid=20 for comparability.

## Guard Policy

- Current MAD guard threshold (implicit in evaluation) produced zero guard triggers. Maintain the threshold; introduce monitoring alert once any guard rate > 0.01 (1%).
- If guard triggers cluster on specific offsets or tags, re-run a focused extended harness to reassess candidate count or distance metric.

## Effectiveness Interpretation

Effectiveness (raw): `ann_speedup * (1 - prune_ratio) - q50_mad`.

Adjusted effectiveness removes warmup/build spikes and large latency outliers (>100 ms build or latency). Retrieval 60m configs retain top raw values (~0.1556) but adjusted value is 0.0 when pruning ratio is exactly 0.8333 with minimal speedup variance *and* the filter excludes all non-outlier points with variation—monitor future runs as the adjusted metric will become more discriminative when variability increases.

## Reconsider Triggers

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Guard trigger rate | > 1% of evaluated windows | Increase ann_max_candidates (e.g. 20 → 30) and re-run tuned harness. |
| q50 MAD (retrieval 60m) | > 0.05 | Run extended harness with candidate ladder (50,30,20) and evaluate speedup/MAD trade-off. |
| Prune ratio (retrieval 60m) | > 0.90 persistently | Expand historical dataset or adjust distance metric (try cosine). |
| Speedup (retrieval 60m) | < 0.85 | Investigate index reuse / caching or increase candidate count modestly. |
| Adjusted effectiveness (120m retrieval) | < 0.05 after prior >0.10 | Re-run extended to confirm not regression in pruning dynamics. |

## Operational Playbook

1. Nightly (optional) lightweight check — run a one-day slice (last 1 trading day) for retrieval 60m k=10 and 120m k=10; compute deltas vs stored baseline.
2. Weekly extended validation — run candidates=50 extended sweep for retrieval only; record top adjusted effectiveness; update history log.
3. Monthly tuning gate — if any trigger threshold breached, reintroduce candidate ladder and/or auto/hybrid for comparison.

## Future Enhancements (Backlog)

- Add weight-sensitivity sweep script to quantify robustness of ranking weights.
- Persist ANN indexes across combos to reduce build_ms and re-measure cumulative harness wall time.
- Introduce guard threshold tuner: search MAD guard that maximizes adjusted effectiveness - penalty(guard_trigger_rate).
- Export historical run metrics to Prometheus for Grafana trend dashboards.

## Artifact Pointers

| Artifact | Path |
|----------|------|
| Tuned Ranking CSV | `results/ann_large_tuned/combined/ann_ranking.csv` |
| Tuned Report | `results/ann_large_tuned/combined/ann_ranking_report.md` |
| Extended Ranking CSV | `results/ann_large_extended/combined/ann_ranking.csv` |
| Tuned vs Extended Diff | `results/ann_large_diff/ann_ranking_diff.md` |

---
Maintainer: (auto-generated draft). Revise wording or thresholds as production observations accrue.
