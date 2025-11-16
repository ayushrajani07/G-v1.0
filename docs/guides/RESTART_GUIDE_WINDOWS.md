# Dashboard API Restart Guide (Windows / PowerShell)

This guide shows reliable ways to stop and start the Dashboard API so new routes (e.g., /api/diag/*) are picked up consistently on Windows.

## Preferred: VS Code Tasks

- Dashboard API: Start on 9500 (reload)
  - Runs the server with auto-reload on port 9500/8003. Use this for normal development.
- Dashboard API: Force Rebind 9500 (reload+verify)
  - Forces a rebind to 9500 and performs a quick verification. Use when reload looks stale or the port is stuck.

Both tasks are already available in this workspace under .vscode/tasks.json.

## Manual cold restart (advanced)

Use this when you suspect the running process isn’t picking up new code or reload is stale.

1) Stop any process bound to 9500

```powershell
Get-NetTCPConnection -LocalPort 9500 -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess
# If a PID is shown, stop it (replace <PID>)
Stop-Process -Id <PID> -Force
# Confirm it’s free
Get-NetTCPConnection -LocalPort 9500 -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess
```

2) Clear module caches for the dashboard app (optional but helpful)

```powershell
$ErrorActionPreference='SilentlyContinue'
Get-ChildItem -Path 'c:\Users\Asus\Desktop\g6_reorganized\src\web\dashboard' -Recurse -Directory -Filter __pycache__ | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
Write-Output 'Cleared __pycache__ under src\\web\\dashboard'
```

3) Start uvicorn with correct PowerShell env syntax

Important: In PowerShell, environment variables must be set via `$env:VAR='value'` before the command. Avoid stray `=1` tokens.

```powershell
Set-Location c:\Users\Asus\Desktop\g6_reorganized
$env:G6_DASHBOARD_DEBUG='1'
$env:PYTHONUNBUFFERED='1'
.\.venv\Scripts\python.exe -m uvicorn src.web.dashboard.app:app --host 127.0.0.1 --port 9500
```

If you prefer reload mode manually:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.web.dashboard.app:app --host 127.0.0.1 --port 9500 --reload
```

## Quick verification

- Integrity: returns 200 and shows `present=true`, `openapi_present=true`.

```powershell
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9500/api/diag/advisor_integrity' | Select-Object -Expand Content
```

- Freshness (Stat panel source): returns JSON with `age_minutes`.

```powershell
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9500/api/ml/universal_advisor/generated_at_age_minutes' | Select-Object -Expand Content
```

- Optional debug: which app file is loaded

```powershell
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9500/api/_which_app_file' | Select-Object -Expand Content
```

## Troubleshooting

- 404 for new endpoints after code changes
  - Do a manual cold restart (stop PID, clear `__pycache__`, start again).
  - Check `/api/_which_app_file` to ensure the running process is loading the expected `src/web/dashboard/app.py`.

- `=1 : The term '=1' is not recognized` in the terminal
  - This indicates incorrect PowerShell env syntax. Use `$env:VAR='value'` lines as shown above.

- Port bind errors (address in use)
  - Free the port by stopping the owning PID (see step 1), or use the VS Code "Force Rebind" task.

## See also

- `GRAFANA_ADVISOR_INTEGRATION.md` for Grafana setup and monitoring panels.
- `scripts/probe_advisor_health.py` for a CLI health probe that checks integrity and freshness.
