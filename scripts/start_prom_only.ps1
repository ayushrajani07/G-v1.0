param(
  [string]$ConfigPath
)

$ErrorActionPreference = 'Continue'

try {
  $repoRoot = Split-Path $PSScriptRoot -Parent
  if (-not $ConfigPath -or -not (Test-Path -LiteralPath $ConfigPath)) {
    $ConfigPath = Join-Path $repoRoot 'prometheus.yml'
  }
  & (Join-Path $PSScriptRoot 'auto_stack.ps1') -StartPrometheus:([bool]$true) -StartInflux:([bool]$false) -StartGrafana:([bool]$false) -PrometheusConfig $ConfigPath
  exit $LASTEXITCODE
} catch {
  try { Write-Host ("start_prom_only.ps1 failed: {0}" -f $_.Exception.Message) -ForegroundColor Red } catch {}
  exit 1
}
