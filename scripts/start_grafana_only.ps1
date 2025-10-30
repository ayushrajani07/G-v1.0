param(
  [switch]$OpenBrowser,
  [switch]$Anonymous
)

$ErrorActionPreference = 'Continue'

try {
  $scriptPath = Join-Path $PSScriptRoot 'auto_stack.ps1'
  if ($OpenBrowser -and $Anonymous) {
    & $scriptPath -StartPrometheus:([bool]$false) -StartInflux:([bool]$false) -StartGrafana:([bool]$true) -GrafanaAllowAnonymous -OpenBrowser
  } elseif ($OpenBrowser) {
    & $scriptPath -StartPrometheus:([bool]$false) -StartInflux:([bool]$false) -StartGrafana:([bool]$true) -OpenBrowser
  } elseif ($Anonymous) {
    & $scriptPath -StartPrometheus:([bool]$false) -StartInflux:([bool]$false) -StartGrafana:([bool]$true) -GrafanaAllowAnonymous
  } else {
    & $scriptPath -StartPrometheus:([bool]$false) -StartInflux:([bool]$false) -StartGrafana:([bool]$true)
  }
  exit $LASTEXITCODE
} catch {
  try { Write-Host ("start_grafana_only.ps1 failed: {0}" -f $_.Exception.Message) -ForegroundColor Red } catch {}
  exit 1
}
