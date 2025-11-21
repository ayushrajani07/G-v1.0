# Dashboard Freeze Guide (G6 Platform)

This guide defines the standard process to permanently (or semi-permanently) lock Grafana dashboards in the G6 platform and ensure reproducible environments.

## 1. Freeze Criteria
A dashboard SHOULD be frozen when:
- It is operationally critical (core monitoring, contracts feed).
- Its schema and visual configuration stabilized.
- Changes require formal review (PR + version tag bump).

## 2. Required JSON Fields
Each frozen dashboard JSON must include:
- `editable: false`
- `g6_lock: true` (custom lock flag)
- `version_tag: freeze-YYYY-MM-DD` (bump on any change)

Optional documentation fields:
- `g6_meta.description` summarizing intent.

## 3. Folder & Provisioning
Use a dedicated folder: `G6 Frozen`.
Provisioning provider example (see `grafana/provisioning/dashboards/frozen_contracts.yml`):
```yaml
providers:
  - name: G6 Frozen Contracts
    orgId: 1
    folder: G6 Frozen
    type: file
    disableDeletion: true
    allowUiUpdates: false
    options:
      path: grafana/dashboards/dashboards_live
```
Permissions: grant Viewer for standard users; Editors only to maintainers.

## 4. CI Enforcement
Workflow checks:
1. If a file under `grafana/dashboards/dashboards_live/` changes and contains `g6_lock": true` then its `version_tag` must change compared to main.
2. `editable` must remain `false`.
3. `g6_lock` must not be removed.

## 5. Freeze Script
Use `scripts/grafana_freeze.ps1` to:
- Freeze a dashboard (inject fields).
- Validate all frozen dashboards.
- Produce a summary table.

Examples:
```powershell
# Freeze a new dashboard by filename (without path)
./scripts/grafana_freeze.ps1 -Freeze contracts_from_csv.json

# Validate all
./scripts/grafana_freeze.ps1 -Validate
```

## 6. Change Procedure
1. Copy the JSON: `cp contracts_from_csv.json contracts_from_csv_WORKING.json`
2. Edit working copy, test locally.
3. Replace original, bump `version_tag` to today.
4. Run `-Validate`.
5. Commit + PR (CI ensures tag bump).

## 7. Unfreeze (Exceptional)
Remove `g6_lock`, set `editable: true`, add comment in PR justification. CI will flag this for manual approval.

## 8. Common Pitfalls
| Issue | Cause | Fix |
|-------|-------|-----|
| PCR line flat | Axis hidden & stacked | Set dedicated axis (already done) |
| Dashboard editable again | Provisioning provider allows UI updates | Set `allowUiUpdates: false` |
| CI failure on tag | Forgot to bump version_tag | Update date to current |

## 9. Future Bundling
Multiple dashboards can share the same provisioning folder. Maintain lock fields in each file.

## 10. References
- Grafana provisioning docs: https://grafana.com/docs/grafana/latest/administration/provisioning/

## 11. Maintainers
Add primary and backup maintainers in CODEOWNERS (future).

---
Revision: 2025-11-21
