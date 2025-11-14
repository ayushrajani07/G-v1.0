param(
    [switch]$Remove,
    [string]$TaskName = "G6 ANN Daily Health Check",
    [string]$Time = "18:05",
    [string]$Days = "Monday,Tuesday,Wednesday,Thursday,Friday",
    [string]$Index = "NIFTY",
    [string]$Tag = "this_week",
    [string]$Offset = "0",
    [int]$DaysBack = 3,
    [int]$MinRows = 5,
    [string]$Baseline = "baselines/ann_daily_baseline.json"
)

$ErrorActionPreference = "Stop"

# Resolve repo root and script path
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$runner = Join-Path $repoRoot "scripts/ml/run_ann_daily_health_check.ps1"

if ($Remove) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "[schedule] Removed task '$TaskName'"
    } catch {
        Write-Warning "[schedule] Could not remove task '$TaskName': $($_.Exception.Message)"
    }
    exit 0
}

if (-not (Test-Path $runner)) {
    throw "Runner script not found: $runner"
}

# Build the action to call PowerShell with our runner and arguments
$psArgs = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', "`"$runner`"",
    '-Index', "`"$Index`"",
    '-Tag', "`"$Tag`"",
    '-Offset', "`"$Offset`"",
    '-DaysBack', $DaysBack,
    '-Baseline', "`"$Baseline`"",
    '-MinRows', $MinRows
)

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($psArgs -join ' ')

# Parse days list into array for New-ScheduledTaskTrigger
$daysArr = @()
foreach ($d in ($Days -split ',')) {
    $trim = $d.Trim()
    if ($trim) { $daysArr += $trim }
}
if ($daysArr.Count -eq 0) { $daysArr = @('Monday','Tuesday','Wednesday','Thursday','Friday') }

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $daysArr -At $Time
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Write-Host "[schedule] Registered '$TaskName' @ $Time on $($daysArr -join ', ')"
Write-Host "[schedule] Action: powershell.exe $($psArgs -join ' ')"
