param(
    [string]$Index = 'NIFTY',
    [string]$Tag = 'this_week',
    [string]$Offset = '0',
    [int]$DaysBack = 3,
    [string]$Baseline = 'baselines/ann_daily_baseline.json',
    [int]$Port = 9308,
    [int]$Interval = 300,
    [int]$MinRows = 5,
    [float]$SpeedupMinDrop = 0.05,
    [float]$MadMax = 0.05,
    [float]$PruneMax = 0.90,
    [switch]$Once,
    [switch]$Verbose,
    [string]$Python = "$PSScriptRoot/../../.venv/Scripts/python.exe"
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$env:PYTHONPATH = $repoRoot
$script = Join-Path $repoRoot 'scripts/ml/ann_health_exporter.py'
if (-not (Test-Path $script)) { throw "Exporter script not found: $script" }

$pyPath = (Resolve-Path $Python).Path
$argList = @(
    $script,
    '--index', $Index,
    '--tag', $Tag,
    '--offset', $Offset,
    '--days-back', $DaysBack,
    '--baseline', (Join-Path $repoRoot $Baseline),
    '--port', $Port,
    '--interval', $Interval,
    '--min-rows', $MinRows,
    '--speedup-min-drop', $SpeedupMinDrop,
    '--mad-max', $MadMax,
    '--prune-max', $PruneMax
)
if ($Verbose) { $argList += '--verbose' }
if ($Once) { $argList += '--once' }

Write-Host "[exporter-start] $pyPath $($argList -join ' ')"
& $pyPath $argList
exit $LASTEXITCODE
