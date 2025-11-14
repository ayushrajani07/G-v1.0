# ANN Health Runbook

_Last updated: 2025-11-08_

## 1. Scope & Purpose
This runbook provides standardized triage and remediation steps for ANN retrieval health issues surfaced via Prometheus alerts and Grafana panels. It covers:
- Understanding key metrics & recording rules
- Alert taxonomy and prioritization
- Baseline refresh decision criteria vs tuning rollback
- Fast investigation checklists
- Edge cases (low rows, new index, market closure)

Applies to indices currently monitored (e.g. `NIFTY`, `BANKNIFTY`) through `ann_health_exporter.py` slices (retrieval k=10 windows 60,120) and daily health checks.

## 2. Core Metrics & Recording Rules
Raw gauges (per index, window):
- `ann_health_speedup` — live retrieval speedup
- `ann_health_prune_ratio` — fraction of candidates pruned (high can signal over-pruning / limited savings)
- `ann_health_q50_mad` — quality dispersion (median absolute deviation proxy)
- `ann_health_rows` — contributing sample rows (data sufficiency gate)
- `ann_health_effectiveness_adjusted` — adjusted effectiveness (or fallback raw effectiveness)
- `ann_health_guard_trigger_rate` — guard trigger frequency (0-1)
- `ann_health_regression_total` — count of regression conditions (speedup drop, MAD > threshold, prune > threshold)
- `ann_health_last_run_timestamp_seconds` — exporter timing

Deltas vs baseline:
- `ann_health_speedup_delta`, `ann_health_prune_ratio_delta`, `ann_health_q50_mad_delta`

Derived / smoothed (recording rules):
- `ann_health_regression_active` (binary smoothing over 5m)
- `ann_health_effectiveness_adjusted_mean_30m`, `ann_health_effectiveness_adjusted_mean_5m`, `ann_health_effectiveness_adjusted_mean_1h`
- `ann_health_speedup_delta_mean_30m`, `ann_health_speedup_delta_mean_5m`, `ann_health_speedup_delta_mean_1h`
- `ann_health_prune_ratio_p95_30m`, `ann_health_prune_ratio_p95_2h`

## 3. Alert Taxonomy & Priority
| Alert | Type | Severity | Core Signal | Typical Cause | Immediate Focus |
|-------|------|----------|-------------|---------------|----------------|
| AnnHealthRegressionDetected | Regression | warning | `regression_total>0` 2m | Transient dip / sparse rows normalized | Validate rows & recent tuning commits |
| AnnHealthRegressionActiveSustained | Regression | warning | Smoothed active >5m | Persistent degradation | Examine speedup/prune trend; gather ranking CSV |
| AnnHealthChronicRegression | Regression | critical | Any regression for 30m | Structural change or baseline stale | Consider baseline refresh or rollback |
| AnnHealthEffectivenessLow | Quality + regression | critical | `effectiveness_adjusted` 15m avg <0.02 & active | Severe quality loss | Inspect candidate counts / pruning heuristics |
| AnnHealthEffectivenessSLOBreach | SLO | warning | 30m mean <0.05 & active | Ongoing deterioration | Decide refresh vs retune |
| AnnHealthPruneRatioP95High | Efficiency | warning | p95 prune >0.90 30m | Over-pruning / inadequate candidate pool | Check candidate limit, speedup delta |
| AnnHealthSpeedupDeltaEroded | Performance | info | 30m speedup delta < -0.05 | Slow resource / tuning regression | Resource constraints or baseline shift |
| AnnHealthEffectivenessFastBurn | SLO burn (fast) | critical | 5m mean <0.03 & 1h mean <0.05 & active | Rapid quality collapse | Immediate containment / rollback |
| AnnHealthEffectivenessSlowBurn | SLO burn (slow) | warning | 30m mean <0.05 & 6h avg <0.06 & active | Long-lived deterioration | Controlled baseline refresh possible |
| AnnHealthSpeedupDeltaBurn | SLO burn | warning | 5m<-0.08 & 1h<-0.05 & active | Fast performance erosion | Check system load & harness changes |
| AnnHealthPruneRatioBurn | SLO burn | warning | p95 30m>0.92 & 2h>0.90 | Sustained high pruning | Candidate cap / pruning logic issue |
| AnnHealthEffectivenessLow + SpeedupDeltaBurn combo | (Implicit) | escalated | Quality + performance | Multi-dimensional failure | Trigger rollback plan |

Escalation order (approx): RegressionDetected < SpeedupDeltaEroded < RegressionActiveSustained < PruneRatioP95High < EffectivenessSLOBreach < ChronicRegression / Burn alerts < EffectivenessLow.

## 4. Fast Triage Checklist (Run in Order)
1. Sanity & Data Sufficiency
   - Confirm `ann_health_rows` >= `min_rows` (baseline & exporter config). If rows low, treat alerts as provisional.
   - Market status: verify session open; if closed or holiday, delays expected.
2. Exporter Health
   - Check last run timestamp; ensure recent (< interval*2). If stale, restart exporter or investigate harness exit.
3. Baseline Validation
   - Compare baseline JSON branch for index vs live metrics. If baseline speedup/prune are outdated (older tuning improvements), consider baseline refresh.
4. Resource & System Signals
   - Look at system latency / memory pressure dashboards for correlated degradation.
5. Harness / Tuning Changes
   - Identify recent commits affecting candidate limits, mode logic, MAD thresholds.
6. Ranking Deep Dive
   - Run `ann_daily_health_check.py` for the index with history logging; examine produced ranking CSV.
7. Decide Path: Refresh vs Retune vs Rollback (see decision tree).

## 5. Decision Tree: Baseline Refresh vs Tuning Rollback
```
                  +-- Rows < min_rows? --> HOLD (collect more data first)
                  |
   Alert Trigger -+-- Rapid burn (EffectivenessFastBurn OR SpeedupDeltaBurn)? --> ROLLBACK recent tuning immediately
                  |
                  +-- ChronicRegression >=30m & effectiveness near previous baseline --> REFRESH baseline if performance acceptable
                  |
                  +-- EffectivenessLow (<0.02) despite healthy resources --> RETUNE (lower prune, adjust candidate limits)
                  |
                  +-- PruneRatioBurn but speedup improving --> RETUNE (increase candidates / adjust pruning thresholds)
                  |
                  +-- SpeedupDeltaEroded only, baseline aged (>7d), no quality loss --> REFRESH baseline (after verifying quality stability)
```
Rollback triggers: Rapid burn + quality collapse OR multi-dimensional failure (EffectivenessLow + SpeedupDeltaBurn).
Refresh prerequisites: Stable quality (`effectiveness_adjusted_mean_30m >= 0.05`), speedup delta within mild erosion (< -0.03), prune ratio not extreme (p95 <0.90), sufficient rows.
Retune scenarios: Over-pruning (high prune p95), high MAD, poor effectiveness without systemic resource issues.

## 6. Baseline Refresh Procedure
1. Run daily health check with conservative window:
   ```
   set PYTHONPATH=... & python scripts/ml/ann_daily_health_check.py --index NIFTY --tag this_week --offset 0 --start <YYYY-MM-DD> --end <YYYY-MM-DD> --baseline baselines/ann_daily_baseline.json --min-rows 5 --history-dir results/ann_daily_check/history --refresh-baseline-if-ok
   ```
2. Ensure output indicates `regressions=0` and each key meets row gate.
3. Verify baseline file diff (only index branch updated in nested format).
4. Commit baseline update with message: `ANN baseline refresh (index=<idx>, windows=60,120)`.

Exporter auto-refresh (when `--refresh-baseline-if-ok` provided) should be used only during stable sessions (avoid early session volatility).

## 7. Retuning Guidelines
Parameter axes:
- Candidate limits (`ann_max_candidates` per mode): Increase moderately if effectiveness low and prune high, decrease if MAD rising.
- Prune heuristics: Adjust threshold decreasing prune if p95 >0.90 continuously.
- MAD guard thresholds: Tighten if quality dispersion (MAD) high; relax if false regressions frequent.
- Mode selection (retrieval vs auto vs hybrid): Re-run extended harness with widened windows for evidence.

Retune Workflow:
1. Generate extended harness slice with broader history (> 7 trading days) for the index.
2. Compare ranking vs baseline using diff script (`ann_compare_tuned_vs_extended.py`).
3. Draft candidate override JSON (auto_tune output) and apply minimal adjustments.
4. Re-evaluate exporter (single-run) and confirm regression_total==0 before enabling auto-refresh.

## 8. Rollback Procedure
Rollback aims to restore last known healthy config set.
1. Identify previous commit containing stable harness overrides or baseline.
2. Revert tuning-related files (harness parameters, override JSONs, baseline if necessary).
3. Clear exporter temp results directory `results/ann_health_exporter_tmp` if stale.
4. Run exporter `--once` for both indices to validate improvement.
5. Monitor alerts for decay; chronic regression should clear within 2 exporter cycles.

## 9. Edge Cases & Special Considerations
- Sparse New Index (e.g., BANKNIFTY initial): Expect near-zero speedup & prune≈1.0; treat early regressions as informational until rows accumulate.
- Holiday / Partial Session: Low rows may trigger apparent regression; suppress manual interventions unless chronic alerts persist post-session.
- Data Gaps: If rows drop suddenly, check upstream collectors and market open flag before retuning.
- Baseline Drift Without Regression: If speedup improves materially (> +0.05 delta sustained) with no regressions, schedule a refresh rather than immediate retune.

## 10. Verification Commands (Examples)
Single-run exporter (diagnostic):
```
set PYTHONPATH=C:\Users\Asus\Desktop\g6_reorganized & python scripts\ml\ann_health_exporter.py --index NIFTY --tag this_week --offset 0 --days-back 3 --baseline baselines\ann_daily_baseline.json --port 9308 --interval 300 --min-rows 5 --verbose --once
```
Daily health check (no refresh):
```
set PYTHONPATH=C:\Users\Asus\Desktop\g6_reorganized & python scripts\ml\ann_daily_health_check.py --index BANKNIFTY --tag this_month --offset 0 --start 2025-11-06 --end 2025-11-08 --baseline baselines\ann_daily_baseline.json --min-rows 5 --history-dir results\ann_daily_check\history
```
Seeding baseline from ranking:
```
set PYTHONPATH=C:\Users\Asus\Desktop\g6_reorganized & python scripts\ml\seed_ann_baseline_from_ranking.py --index BANKNIFTY --ranking results\ann_seed_banknifty_sm\combined\ann_ranking.csv --baseline baselines\ann_daily_baseline.json
```

## 11. Reference Thresholds (Current Defaults)
- Speedup drop regression: live < baseline - 0.05
- MAD max: 0.05
- Prune ratio max: 0.90 (warn) / burn escalation >0.92 (30m) & >0.90 (2h)
- Effectiveness SLO: 30m mean >= 0.05 (warning below), critical under 0.02 (15m avg)
- Speedup delta erosion: 30m mean < -0.05 (info) / fast burn 5m < -0.08 + 1h < -0.05

## 12. Post-Remediation Validation
After refresh / retune / rollback:
1. Exporter run shows `regression_total=0` for two consecutive intervals.
2. Burn alerts clear; effectiveness 30m mean rises above 0.05.
3. Prune ratio p95 trending downward (<0.88) if previously elevated.
4. Commit containing remediation annotated in CHANGELOG or a dedicated ANN section.

## 13. Future Enhancements (Backlog)
- Composite ANN health score gauge (blend of regression_active + normalized speedup delta + effectiveness + prune p95).
- Automated baseline refresh scheduler (skip volatile first hour of session).
- Alert suppression logic for known low-rows windows (pre-open or illiquid days).

## 14. Quick Reference Summary
| Action | When | Command / Step |
|--------|------|----------------|
| Baseline Refresh | Stable metrics, regressions cleared, aged baseline | Daily health check with `--refresh-baseline-if-ok` |
| Retune | Quality low OR prune p95 high OR speedup erosion without systemic issues | Extended harness + auto_tune overrides |
| Rollback | Fast burn + effectiveness collapse OR multi-dimensional failure | Revert tuning commits + restore prior baseline |
| Seed New Index | Initial sparse metrics | Seeding script from ranking CSV |
| Validate Recovery | After any remediation | Exporter `--once` + check alerts clear |

---
_Keep this document updated whenever thresholds or alert logic change._
