param(
  [int[]]$Ports = @(9500,9108,9109,3002,9091),
  [switch]$AlsoPython
)

Write-Host '=== Stopping G6 Stack Processes ===' -ForegroundColor Cyan

function Stop-ByName {
  param([string[]]$Names)
  foreach ($n in $Names) {
    try {
      $procs = Get-Process -Name $n -ErrorAction SilentlyContinue
      if ($procs) {
        $ids = ($procs | Select-Object -ExpandProperty Id) -join ','
        Write-Host ("Stopping {0} (PIDs: {1})" -f $n, $ids) -ForegroundColor Yellow
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
      }
    } catch {}
  }
}

function Stop-ByPort {
  param([int]$Port)
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processIdVar in $conns) {
      try {
        $p = Get-Process -Id $processIdVar -ErrorAction SilentlyContinue
        if ($p) {
          Write-Host ("Stopping PID {0} (port {1}, name {2})" -f $processIdVar, $Port, $p.ProcessName) -ForegroundColor Yellow
          Stop-Process -Id $processIdVar -Force -ErrorAction SilentlyContinue
        }
      } catch {}
    }
  } catch {}
}

# Known service names
Stop-ByName -Names @('grafana-server','prometheus','influxd')

# If requested, also stop any lingering python processes
if ($AlsoPython) { Stop-ByName -Names @('python','python3','py') }

# Stop by known/bound ports
foreach ($p in $Ports) { Stop-ByPort -Port $p }

Write-Host 'Done.' -ForegroundColor Green
