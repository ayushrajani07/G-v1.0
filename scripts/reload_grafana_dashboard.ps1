# Reload Grafana Dashboard
# Copies dashboard from live to provisioning and restarts Grafana

Write-Host "Copying dashboard to provisioning..."
Copy-Item "C:\GrafanaData\dashboards_live\overlays.json" "C:\GrafanaData\provisioning_baseline\dashboards_src\overlays.json" -Force
Write-Host "[OK] Dashboard copied"

Write-Host "Stopping Grafana..."
$grafanaProcs = Get-Process | Where-Object { $_.ProcessName -match "grafana" }
if ($grafanaProcs) {
    $grafanaProcs | Stop-Process -Force
    Write-Host "[OK] Grafana stopped ($($grafanaProcs.Count) process(es))"
} else {
    Write-Host "[INFO] No Grafana processes running"
}

Start-Sleep -Seconds 2

Write-Host "Starting Grafana..."
Start-Process -FilePath "C:\Grafana\grafana-v11.2.0\bin\grafana-server.exe" `
    -ArgumentList "--homepath=C:\Grafana\grafana-v11.2.0", "--config=C:\Grafana\grafana-v11.2.0\conf\custom.ini" `
    -WindowStyle Hidden

Write-Host "Waiting for Grafana to start (12 seconds)..."
Start-Sleep -Seconds 12

Write-Host "Checking Grafana health..."
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:3002/api/health" -TimeoutSec 3 | Out-Null
    Write-Host "[OK] Grafana is ready!"
    Write-Host "Opening dashboard..."
    Start-Process "http://127.0.0.1:3002/d/g6-overlays"
} catch {
    Write-Host "[ERROR] Grafana health check failed: $_"
    Write-Host "You may need to wait a bit longer and open manually: http://127.0.0.1:3002/d/g6-overlays"
}
