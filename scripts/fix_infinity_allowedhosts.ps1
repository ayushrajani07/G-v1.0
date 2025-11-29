# Fix Infinity Datasource Allowed Hosts
# Run this ONCE after starting the observability stack

param(
    [int]$WebPort = 9500,
    [int]$GrafanaPort = 3002
)

Write-Host "Configuring Infinity datasource allowedHosts..." -ForegroundColor Cyan

# Get current datasource config
try {
    $ds = Invoke-RestMethod "http://127.0.0.1:$GrafanaPort/api/datasources/uid/INFINITY" -TimeoutSec 5
    
    # Update with allowedHosts
    $ds.jsonData = @{
        allowedHosts = @(
            "http://127.0.0.1:$WebPort",
            "http://localhost:$WebPort",
            "127.0.0.1:$WebPort",
            "localhost:$WebPort"
        )
    }
    
    # Remove read-only fields
    $ds.PSObject.Properties.Remove('version')
    $ds.PSObject.Properties.Remove('created')
    $ds.PSObject.Properties.Remove('updated')
    
    # Convert to JSON
    $body = $ds | ConvertTo-Json -Depth 10
    
    # Update datasource
    $result = Invoke-RestMethod -Uri "http://127.0.0.1:$GrafanaPort/api/datasources/$($ds.id)" -Method Put -ContentType "application/json" -Body $body -ErrorAction Stop
    
    Write-Host "SUCCESS! Infinity datasource configured" -ForegroundColor Green
    Write-Host "AllowedHosts: $($ds.jsonData.allowedHosts -join ', ')" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Now refresh your dashboard: http://127.0.0.1:$GrafanaPort/d/g6-table-test" -ForegroundColor Cyan
    
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Manual fix required:" -ForegroundColor Yellow
    Write-Host "1. Go to: http://127.0.0.1:$GrafanaPort/connections/datasources/edit/INFINITY" -ForegroundColor White
    Write-Host "2. Scroll to 'Allowed Hosts'" -ForegroundColor White
    Write-Host "3. Add: http://127.0.0.1:$WebPort" -ForegroundColor White
    Write-Host "4. Click 'Save & Test'" -ForegroundColor White
}
