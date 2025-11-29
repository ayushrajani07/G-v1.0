Param(
  [string]$PromtoolPath = "promtool"
)

Write-Host "Checking Prometheus rules..."
if (-not (Get-Command $PromtoolPath -ErrorAction SilentlyContinue)) {
  Write-Error "promtool not found in PATH. Install Prometheus or supply -PromtoolPath."; exit 1
}
& $PromtoolPath check rules "$PSScriptRoot/../prometheus_alerts_drift.yml"
if ($LASTEXITCODE -ne 0) { Write-Error "Alert rules failed validation"; exit 1 }
& $PromtoolPath check rules "$PSScriptRoot/../prometheus_recording_rules_generated.yml"
if ($LASTEXITCODE -ne 0) { Write-Error "Recording rules failed validation"; exit 1 }
Write-Host "Prometheus rule validation passed."