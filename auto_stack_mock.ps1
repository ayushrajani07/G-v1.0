param(
  [switch]$NoProm,
  [string]$PrometheusExe,
  [string]$PromConfig,
  [switch]$OpenBrowser
)

$ErrorActionPreference = 'Continue'

try {
  $repoRoot = Split-Path $MyInvocation.MyCommand.Path -Parent
  $scriptPath = Join-Path $repoRoot 'scripts/auto_stack.ps1'
  if (-not (Test-Path -LiteralPath $scriptPath)) {
    Write-Host "auto_stack.ps1 not found at $scriptPath" -ForegroundColor Red
    exit 1
  }

  # Default: start Grafana and Influx; optionally skip Prometheus
  $startProm = -not $NoProm.IsPresent

  # Directly invoke the main script so switch parameters bind correctly
  if ($PromConfig) {
    & $scriptPath -StartPrometheus:([bool]$startProm) -StartInflux:$true -StartGrafana:$true -PrometheusConfig $PromConfig @([string[]]($(if ($OpenBrowser){'-OpenBrowser'})))
  } else {
    & $scriptPath -StartPrometheus:([bool]$startProm) -StartInflux:$true -StartGrafana:$true @([string[]]($(if ($OpenBrowser){'-OpenBrowser'})))
  }
  exit $LASTEXITCODE
} catch {
  try { Write-Host ("auto_stack_mock.ps1 failed: {0}" -f $_.Exception.Message) -ForegroundColor Red } catch {}
  exit 1
}
