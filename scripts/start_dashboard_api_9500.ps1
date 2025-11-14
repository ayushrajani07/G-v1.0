param(
    [switch]$Reload,
    [int[]]$KillPorts = @(9500, 8003)
)

# Kill any processes listening on the specified ports (default: 9500 and 8003)
try {
    foreach ($port in $KillPorts) {
        try {
            $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($conns) {
                $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
                foreach ($pid in $pids) {
                    try {
                        Write-Host "Stopping process on port $port (PID=$pid)" -ForegroundColor Yellow
                        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                    } catch {}
                }
                Start-Sleep -Milliseconds 300
            }
        } catch {}
    }
} catch {}

# Pick Python
$python = $env:VIRTUAL_ENV + "\Scripts\python.exe"
if (!(Test-Path $python)) {
    $python = "py"
}

$reloadFlag = ""
if ($Reload) { $reloadFlag = "--reload" }

Write-Host "Starting Dashboard API on 9500..." -ForegroundColor Cyan
& $python "scripts/start_dashboard_api.py" $reloadFlag --ports 9500
