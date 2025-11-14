param(
    [string]$Indices = "NIFTY",
    [string]$Horizons = "30,60",
    [int]$WindowMinutes = 180,
    [double]$Target = 0.8,
    [string]$BaseUrl = "http://127.0.0.1:9500",
    [string]$ExpiryTag = "this_week",
    [string]$Offset = "0",
    [string]$DateStr = "",
    [string]$Python = "python",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

# Resolve repo root relative to this script
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$py = $Python

# If a local venv exists, prefer it
try {
    $venvPy = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { $py = $venvPy }
} catch {}

$scriptPath = Join-Path $repoRoot "scripts\ml\calibrate_bands.py"
if (-not (Test-Path $scriptPath)) {
    Write-Error "calibrate_bands.py not found at $scriptPath"
    exit 2
}

$cmd = @(
    "`"$py`"",
    "`"$scriptPath`"",
    "--indices", "`"$Indices`"",
    "--horizons", "`"$Horizons`"",
    "--window-minutes", $WindowMinutes,
    "--target", $Target,
    "--base-url", "`"$BaseUrl`"",
    "--expiry-tag", "`"$ExpiryTag`"",
    "--offset", "`"$Offset`""
)
if ($DateStr) { $cmd += @("--date-str", "`"$DateStr`"") }
if ($Quiet) { $cmd += @("--quiet") }

Write-Output ("Running: " + ($cmd -join ' '))
& $py $scriptPath --indices "$Indices" --horizons "$Horizons" --window-minutes $WindowMinutes --target $Target --base-url "$BaseUrl" --expiry-tag "$ExpiryTag" --offset "$Offset" $(if ($DateStr) {"--date-str `"$DateStr`""} else {""}) $(if ($Quiet) {"--quiet"} else {""})

exit $LASTEXITCODE
