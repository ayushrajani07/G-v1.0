Param(
  [string]$Indices = $env:G6_DRIFT_INDICES,
  [string]$Output = "reports/drift/$(Get-Date -Format yyyy-MM-dd).json",
  [string]$TextfileDir = "reports/drift/textfile"
)

if (-not $Indices) { $Indices = "NIFTY" }

$python = "$PSScriptRoot/../../.venv/Scripts/python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "Running daily drift report for indices=$Indices output=$Output"
& $python scripts/ml/report_drift_daily.py --indices $Indices --output $Output --textfile-dir $TextfileDir --pretty
if ($LASTEXITCODE -ne 0) { Write-Error "Daily drift report failed"; exit 1 }

Write-Host "Daily drift report generated: $Output"
Write-Host "Prometheus textfile (if enabled) in: $TextfileDir/drift_daily.prom"
