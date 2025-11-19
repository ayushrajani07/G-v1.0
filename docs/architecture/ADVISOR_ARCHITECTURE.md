# Universal Advisor Architecture

## Overview
A plugin-based engine providing unified prognosis, diagnosis, and remedy recommendations across ANN retrieval health, Path Forecast ribbon metrics, and expiry coverage. Accessible via `/api/ml/universal_advisor`.

## Components
- Core Engine (`src/advisor/core.py`): Runs registered plugins, aggregates findings, computes health score, emits flags.
- Plugins (`src/advisor/plugins/`):
  - `ann_plugin.py`: ANN speedup, prune, MAD, effectiveness evaluation vs baseline.
  - `path_plugin.py`: Wraps existing path advisor endpoint for coverage, samples, fallback mode.
  - `expiry_plugin.py`: Scans logs for missing logical expiries.
- Prometheus / Exporter Integration (`src/advisor/prom_query.py`): Fetch live ANN metrics via Prometheus or direct scrape.

## Data Model (Simplified)
```
report = {
  generated_at, summary: {overall_level, health_score, per_index: {INDEX:{health_score,level}}, actions_ordered, plugin_health},
  metrics: [{name,value,labels,source,ts}],
  findings: [{code,plugin,severity,summary,evidence,confidence}],
  diagnoses: [...future],
  prognoses: [...future],
  remedies: [{code,steps,automated,preconditions,priority,references}],
  flags: {code:1,...}
}
```

## Health Score Heuristic
Start at 100; subtract 25 per critical finding, 10 per warning (non-critical). Clamp 0..100. Overall level determined by highest severity present.

## Extensibility
Add new plugin:
1. Create `src/advisor/plugins/<your_plugin>.py` implementing `collect_and_evaluate(ctx)`.
2. Register in `build_default_engine` inside `core.py`.
3. Return `PluginResult` with metrics/findings/remedies.

## API Usage
```
GET /api/ml/universal_advisor?indices=NIFTY,BANKNIFTY,SENSEX&windows=60,120&detail=true
```
- `detail=false` returns only summary + flags for lightweight polling.
- Use `use_prometheus=true&prometheus=http://127.0.0.1:9090` to switch to Prometheus queries.

## Remedy Prioritization
Sorted by `priority` descending. High-level codes: rollback > retune > calibrate > refresh > monitor. ANN rollback prioritized when effectiveness low plus speedup/prune degradations.

## Correlation Layer (New)
`correlation_plugin.py` consumes cumulative findings via `ctx.cache['findings']` and emits composite findings/metrics.

Initial rule: ANN effectiveness low (crit) AND Path coverage gap or fallback mode -> `advisor_composite_ann_path_risk` (crit) + metric `advisor_composite_risk{index,type="ann_path"}`.

## Roadmap
- Additional composite rules (expiry gaps + path fallback, multi-index systemic ANN regressions).
- Trend / slope-based prognoses (burn-rate multi-window).
- Automated action trigger endpoints (optional gated by feature flag).
- Persistent advisory history for backtesting remediation effectiveness.
- ML-based classifier for diagnosis confidence improvements.

## References
- `ANN_RUNBOOK.md` for tuning and rollback flows.
- `ML_README.md` for path forecast calibration procedures.
