param(
    [string]$Index = "NIFTY",
    [string]$Tag = "this_week",
    [string]$Offset = "0",
    [int]$DaysBack = 3,
    [string]$Baseline = "baselines/ann_daily_baseline.json",
    [int]$MinRows = 5,
    [string]$Python = "$PSScriptRoot/../../.venv/Scripts/python.exe"
)

$ErrorActionPreference = "Stop"

# Resolve repo root (two levels up from scripts/ml)
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$env:PYTHONPATH = $repoRoot

# Compute date window ending today, spanning DaysBack days
$end = (Get-Date).ToString('yyyy-MM-dd')
if ($DaysBack -lt 1) { $DaysBack = 1 }
$start = (Get-Date).AddDays(-1 * ($DaysBack - 1)).ToString('yyyy-MM-dd')

$pyPath = (Resolve-Path $Python).Path
$script = Join-Path $repoRoot "scripts/ml/ann_daily_health_check.py"

Write-Host "[run-health] $pyPath $script --index $Index --tag $Tag --offset $Offset --start $start --end $end --baseline $Baseline --min-rows $MinRows"

& $pyPath $script --index $Index --tag $Tag --offset $Offset --start $start --end $end --baseline (Join-Path $repoRoot $Baseline) --min-rows $MinRows
exit $LASTEXITCODE
