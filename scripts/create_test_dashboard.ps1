$simpleDashboard = @"
{
  "dashboard": {
    "title": "G6 Live CSV Test",
    "tags": ["g6", "test"],
    "timezone": "Asia/Kolkata",
    "schemaVersion": 39,
    "version": 0,
    "refresh": "30s",
    "time": {
      "from": "now-6h",
      "to": "now"
    },
    "panels": [
      {
        "id": 1,
        "type": "timeseries",
        "title": "NIFTY TP (Live CSV)",
        "gridPos": {"h": 8, "w": 24, "x": 0, "y": 0},
        "targets": [
          {
            "refId": "A",
            "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": "INFINITY"},
            "type": "json",
            "source": "url",
            "format": "table",
            "url": "http://127.0.0.1:9500/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0&limit=500",
            "root_selector": "",
            "columns": [
              {"selector": "time", "text": "Time", "type": "timestamp"},
              {"selector": "tp", "text": "TP", "type": "number"}
            ]
          }
        ]
      }
    ]
  },
  "overwrite": true
}
"@

try {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:3002/api/dashboards/db" -Method POST -Body $simpleDashboard -ContentType "application/json"
    Write-Host "✓ Dashboard created successfully!" -ForegroundColor Green
    Write-Host "UID: $($response.uid)"
    Write-Host "URL: http://127.0.0.1:3002$($response.url)"
    Write-Host ""
    Write-Host "Opening dashboard..." -ForegroundColor Cyan
    Start-Sleep -Seconds 1
    Start-Process "http://127.0.0.1:3002$($response.url)"
} catch {
    Write-Host "✗ Dashboard creation failed" -ForegroundColor Red
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Yellow
    if ($_.ErrorDetails.Message) {
        $details = $_.ErrorDetails.Message
        Write-Host "Details: $details" -ForegroundColor Yellow
    }
}
