# Grafana Advisor Integration Guide

This guide explains how to wire the universal advisor endpoints into Grafana (Infinity datasource) and add simple monitoring/probes for reliability.

## Endpoints Summary
| Purpose | Path | Notes |
|---------|------|-------|
| Full advisor report | `/api/ml/universal_advisor` | Use `detail=true` to include full metrics evidence (default already true). |
| Health (light payload) | `/api/ml/universal_advisor/health` | Designed for Stat / Table panels needing freshness + counts. |
| Age (minutes since generation) | `/api/ml/universal_advisor/generated_at_age_minutes` | Returns `{ age_minutes, generated_at }`. |
| Integrity (diagnostic) | `/api/diag/advisor_integrity` | Consolidated presence + OpenAPI + latest snapshot; 503 if incomplete. |
| Latest route snapshot | `/api/diag/route_snapshot` | Raw snapshot file content for deep debugging. |

## Recommended Panels

### 1. Age Stat Panel
Infinity Query (JSON API):
- URL: `http://127.0.0.1:9500/api/ml/universal_advisor/generated_at_age_minutes`
- Parsing: Response is an object; set `Value field` to `age_minutes`.
- Thresholds example: Warn > 5, Critical > 15 minutes.

### 2. Health Table Panel
- URL: `http://127.0.0.1:9500/api/ml/universal_advisor/health`
- Fields to visualize: `generated_at`, `overall_level`, `counts.findings`, `counts.remedies`.
- Optionally map `overall_level` to color (ok=green, warn=yellow, crit=red).

### 3. Full Advisor Findings Table
- URL: `http://127.0.0.1:9500/api/ml/universal_advisor?detail=true`
- Transform (Infinity): Use a JSON flatten; path to findings array: `findings`.
- Columns: `level`, `code`, `message`, `prognosis`, `remedy`.

### 4. Integrity / Availability Stat
- URL: `http://127.0.0.1:9500/api/diag/advisor_integrity`
- If HTTP 200 -> show OK. If 503 -> show FAIL.
- Value field: `present` (boolean -> map to 1/0). Alternatively derive from `found_count`.

### 5. Snapshot Diff (Optional Debug Panel)
- URL: `http://127.0.0.1:9500/api/diag/route_snapshot`
- Show `snapshot.route_count` and `snapshot.advisor_paths` for quick divergence checks.

## Example Dashboard Variables
```
index: NIFTY
indices: NIFTY,BANKNIFTY
horizons: 60
windows: 60,120
```
Use Infinity variable queries hitting `/api/ml/universal_advisor?detail=false` if you later expand multi-index support.

## Alerting Suggestions
1. Advisor Age Stale:
   - Query age endpoint; alert if `age_minutes > 15` for `NIFTY`.
2. Advisor Integrity Failure:
   - Query `/api/diag/advisor_integrity`; trigger alert if status != 200.
3. Missing Routes Regression:
   - Panel based on `found_count`; alert if `< 3`.

## Synthetic Probe (CLI)
Use the provided script `scripts/probe_advisor_health.py` (see below) in a scheduled task every minute. Non-zero exit signals issue for external monitoring.

## Troubleshooting
| Symptom | Cause | Action |
|---------|-------|--------|
| 503 from integrity endpoint | One or more endpoints missing or OpenAPI not updated yet | Restart API, inspect `logs/webapi_route_snapshot_*.json`. |
| Age always near zero | Very frequent advisor recomputation (expected) | Adjust scrape interval or ignore small ages (<1 min). |
| Age grows despite health OK | Engine not recomputing; stale cache | Restart exporter or investigate advisor engine run frequency. |
| OpenAPI missing advisor paths but integrity present=false | Router inclusion failed; fallback may not have executed | Hit `/api/_advisor_force` (if still present) or restart server. |

## Script: probe_advisor_health.py
Added under `scripts/` to integrate with Windows Task Scheduler.

## Optional Prometheus Recording
If you add a Prometheus push/scrape, consider exporting a gauge:
- `g6_advisor_age_minutes`
- `g6_advisor_integrity_present` (1/0)

You can build this by extending the exporter or adding a metrics adapter later.

## Next Extensions
- Add per-index breakdown endpoint (future): `/api/ml/universal_advisor/indices`.
- Expose advisor metrics as a text Prometheus endpoint. 

---
Last updated: 2025-11-09
