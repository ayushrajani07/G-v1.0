param(
    [int]$Port = 9500,
    [string]$PidEndpoint = "http://127.0.0.1:$Port/__diag/pid"
)

Write-Host "Stopping FastAPI dashboard on port $Port"

function Get-PortPids {
    param([int]$Port)
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
        if ($null -eq $conns) { return @() }
        return $conns | Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique
    } catch {
        # Fallback to netstat if Get-NetTCPConnection not available
        $lines = netstat -ano | Select-String ":$Port" | ForEach-Object { $_.ToString() }
        $pids = @()
        foreach ($l in $lines) {
            $parts = $l -split "\s+"
            if ($parts.Length -ge 5) {
                $procId = $parts[-1]
                if ($procId -match '^[0-9]+$') { $pids += [int]$procId }
            }
        }
        return $pids | Sort-Object -Unique
    }
}

# Try to fetch PID from diagnostics endpoint first
$diagPid = $null
try {
    $resp = Invoke-RestMethod -Uri $PidEndpoint -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($resp -and $resp.pid) { $diagPid = [int]$resp.pid }
} catch {}

if ($diagPid) {
    Write-Host "Stopping PID (diag): $diagPid"
    try { Stop-Process -Id $diagPid -Force -ErrorAction SilentlyContinue } catch {}
}

# Also stop any process currently bound to the port
$pids = Get-PortPids -Port $Port
foreach ($proc in $pids) {
    Write-Host "Stopping PID (port $Port): $proc"
    try { Stop-Process -Id $proc -Force -ErrorAction SilentlyContinue } catch {}
}

# Wait up to ~10s for port to be free
$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline) {
    $p = Get-PortPids -Port $Port
    if ($p.Count -eq 0) { break }
    Start-Sleep -Milliseconds 300
}

$remaining = Get-PortPids -Port $Port
if ($remaining.Count -eq 0) {
    Write-Host "Port $Port is free. Dashboard stopped."
    exit 0
} else {
    Write-Host "Warning: Port $Port still in use by: $($remaining -join ', ')" -ForegroundColor Yellow
    exit 1
}