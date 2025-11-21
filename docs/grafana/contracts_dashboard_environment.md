# G6 Contracts Dashboard (Frozen Version)

Dashboard UID: `g6-contracts-csv`
Version Tag: `freeze-2025-11-21`
Lock Flags: `editable=false`, `g6_lock=true`

## Purpose
Displays live index price, option open interest (call/put), option volume (call/put), and Put-Call Ratio (PCR) for NIFTY, SENSEX, BANKNIFTY, FINNIFTY pulled from the CSV-backed live API with Infinity datasource.

## Required Components
1. Web API (FastAPI) providing `/api/live_csv` endpoint.
   - Must run on `127.0.0.1:9510` or update URLs in the dashboard.
   - Endpoint supports query params: `index`, `expiry_tag`, `offset`, `include_index`, `include_oi`, `include_volume`, `include_pcr`.
2. Grafana
   - Version ≥ 9 (schemaVersion 39 used; works on 9/10).
   - Infinity datasource plugin (`yesoreyeram-infinity-datasource`).
3. (Optional) Prometheus if additional panels referencing metrics are later appended.

## Environment Variables (Recommended)
Set in shell running the collector / API:
- `G6_COLLECTOR_STRICT_SIGNALS=1`
- `G6_COLLECTOR_WATCHDOG=1`
- `G6_COLLECTOR_STALL_TIMEOUT_SEC=40`
(These do not affect Grafana directly but stabilize data feed.)

## Data Field Expectations
Each JSON row returned by `/api/live_csv` must include:
```
index_price (float)
pcr (float)
ce_oi (int/float)
pe_oi (int/float)
ce_vol (int/float)
pe_vol (int/float)
time_str (ISO8601 string)
```
If any field is absent, the corresponding series will be empty.

## Collection Timing
- Refresh interval: 15s.
- Time range default: `now-12h` to `now+6h` (future window enables viewing forward region without changing range).

## PCR Visualization Rules
- PCR now has independent right axis (not stacked) to preserve trend fidelity.
- Stacking disabled for all series (`mode=none`).

## How To Deploy (Provisioning)
Place `contracts_from_csv.json` under a provisioning dashboards directory, e.g.:
```
provisioning/dashboards/contracts/
```
Sample provisioning YAML snippet:
```yaml
apiVersion: 1
providers:
  - name: 'g6-frozen-contracts'
    orgId: 1
    folder: 'G6 Frozen'
    type: file
    disableDeletion: true
    allowUiUpdates: false
    updateIntervalSeconds: 600
    options:
      path: /absolute/path/to/grafana/dashboards/dashboards_live
      foldersFromFilesStructure: true
```
Ensure Grafana service account has read-only access to the path.

## Operational Freeze Steps
1. Commit this dashboard JSON (done) and enforce code-owner review for future changes.
2. Set Grafana folder permissions: viewers only (no editors) for 'G6 Frozen'.
3. In Grafana UI, verify `editable` field is respected (no edit controls).
4. Monitor Infinity query health: query inspector should show HTTP 200 and non-empty arrays.

## Health Checks
- API health endpoint: `http://127.0.0.1:9510/health` (implement if missing).
- Optional custom: `/api/live_csv_health?index=NIFTY&expiry_tag=this_week&offset=0` returning status JSON.

## Recovery / Update Procedure
To modify after freeze:
1. Copy current JSON to `contracts_from_csv_WORKING.json`.
2. Edit working copy; test locally.
3. Replace original file; bump `version_tag` (e.g., `freeze-2025-12-01`).
4. Commit & review.

## Validation Script (Quick Check)
Run:
```powershell
Invoke-WebRequest 'http://127.0.0.1:9510/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0&include_index=1&include_oi=1&include_volume=1&include_pcr=1&limit=3' | Select-Object -ExpandProperty Content
```
Should return JSON array with required keys.

## Known Limitations
- Large OI/Volume magnitudes may still visually dominate; enable log scale if needed.
- Future schema changes to `/api/live_csv` require dashboard URL updates.

## Change History
- 2025-11-21: Added PCR dedicated axis & disabled stacking; frozen.

## Contact
For updates: refer to repository `G-v1.0` PR process (Phase 10 branch) or designated maintainer.
