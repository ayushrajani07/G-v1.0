param(
  [ValidateSet('obs','obs-stop','summary','orchestrator','mock','ws','panels-flow')]
  [string]$Mode = 'obs',

  # Common
  [string]$StatusFile = 'data/runtime_status.json',

  # Observability (Grafana + Web API)
  [int]$GrafanaPort = 3002,
  [int]$WebPort = 9500,
  [switch]$OpenBrowser,
  [switch]$StartPrometheus,
  [int]$PrometheusPort = 9091,
  [string]$GrafanaDataRoot = 'C:\GrafanaData',

  # Orchestrator
  [int]$Interval = 60,
  [int]$Cycles = 0,
  [switch]$Attach,

  # WebSocket service
  [int]$WsPort = 8765,
  [string]$ListenHost = '127.0.0.1',

  # Panels flow
  [string]$PanelsDir = 'data/panels',
  [double]$Refresh = 0.5
)

$ErrorActionPreference = 'Stop'

function Resolve-Python {
  $root = Split-Path $PSScriptRoot -Parent
  $venv = Join-Path $root '.venv\Scripts\python.exe'
  if (Test-Path $venv) { return $venv }
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  throw 'Python not found (expected .venv or system python on PATH).'
}

switch ($Mode) {
  'obs' {
    $obsArgs = @(
      '-GrafanaPort', $GrafanaPort,
      '-WebPort', $WebPort,
      '-GrafanaDataRoot', $GrafanaDataRoot
    )
    if ($OpenBrowser) { $obsArgs += '-OpenBrowser' }
    if ($StartPrometheus) {
      $obsArgs += '-StartPrometheus'
      $obsArgs += @('-PrometheusPort', $PrometheusPort)
    }

    Write-Host "[G6] Starting observability stack (Grafana + Web API)" -ForegroundColor Cyan
    & "$PSScriptRoot\obs_start_clean.ps1" @obsArgs
    break
  }

  'obs-stop' {
    Write-Host "[G6] Stopping observability stack" -ForegroundColor Cyan
    & "$PSScriptRoot\obs_stop.ps1" -GrafanaPort $GrafanaPort
    break
  }

  'summary' {
    $py = Resolve-Python
    Write-Host "[G6] Starting summary UI" -ForegroundColor Cyan
    & $py -m scripts.summary.app --refresh $Refresh --status-file $StatusFile
    break
  }

  'orchestrator' {
    $py = Resolve-Python
    if ($Attach) {
      $env:G6_TERMINAL_MODE = 'attach'
    }
    Write-Host "[G6] Starting orchestrator loop (interval=$Interval cycles=$Cycles)" -ForegroundColor Cyan
    & $py scripts/run_orchestrator_loop.py --config config/g6_config.json --interval $Interval --cycles $Cycles --runtime-status-file $StatusFile
    break
  }

  'mock' {
    $env:G6_USE_MOCK_PROVIDER = '1'
    if ($Attach) {
      $env:G6_TERMINAL_MODE = 'attach'
    }
    $py = Resolve-Python
    Write-Host "[G6] Starting MOCK orchestrator loop (interval=$Interval)" -ForegroundColor Cyan
    & $py scripts/run_orchestrator_loop.py --config config/g6_config.json --interval $Interval --cycles $Cycles --runtime-status-file $StatusFile --auto-snapshots
    break
  }

  'ws' {
    Write-Host "[G6] Starting WebSocket status service" -ForegroundColor Cyan
    & "$PSScriptRoot\start_ws_service.ps1" -StatusFile $StatusFile -Port $WsPort -ListenHost $ListenHost
    break
  }

  'panels-flow' {
    Write-Host "[G6] Starting simulator + panels + summary" -ForegroundColor Cyan
    & "$PSScriptRoot\start_panels_flow.ps1" -StatusFile $StatusFile -PanelsDir $PanelsDir -IntervalSec $Interval -BridgeRefresh $Refresh
    break
  }
}
