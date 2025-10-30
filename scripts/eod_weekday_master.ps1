# EOD Weekday Master Update Script
# Runs end-of-day weekday master updates with quality reporting

param(
    [string]$Date,           # Optional: YYYY-MM-DD (default: today)
    [switch]$Force,          # Force update on non-trading days
    [switch]$DryRun,         # Show what would be done
    [switch]$Verbose,        # Verbose logging
    [switch]$Schedule        # Show how to schedule this script
)

$Root = $PSScriptRoot | Split-Path -Parent
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$Script = Join-Path $Root 'scripts\eod_weekday_master.py'

# Show scheduling instructions
if ($Schedule) {
    Write-Host ""
    Write-Host "=== EOD Weekday Master - Scheduling Instructions ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Windows Task Scheduler:" -ForegroundColor Yellow
    Write-Host "  1. Open Task Scheduler (taskschd.msc)" -ForegroundColor White
    Write-Host "  2. Create Basic Task..." -ForegroundColor White
    Write-Host "     Name:     EOD Weekday Master Update" -ForegroundColor Gray
    Write-Host "     Trigger:  Daily at 16:00 (4:00 PM)" -ForegroundColor Gray
    Write-Host "     Action:   Start a program" -ForegroundColor Gray
    Write-Host "     Program:  powershell.exe" -ForegroundColor Gray
    Write-Host "     Arguments: -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -ForegroundColor Gray
    Write-Host "     Start in: $Root" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Alternative: Use provided setup script" -ForegroundColor Yellow
    Write-Host "  .\scripts\setup_eod_schedule.ps1" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Linux/Mac cron:" -ForegroundColor Yellow
    Write-Host "  # Run at 4:00 PM IST on weekdays" -ForegroundColor Gray
    Write-Host "  0 16 * * 1-5 cd $Root && python scripts/eod_weekday_master.py" -ForegroundColor Gray
    Write-Host ""
    exit 0
}

# Check prerequisites
if (-not (Test-Path $VenvPython)) {
    Write-Host "ERROR: Virtual environment not found at $VenvPython" -ForegroundColor Red
    Write-Host "Please run: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $Script)) {
    Write-Host "ERROR: Script not found at $Script" -ForegroundColor Red
    exit 1
}

# Build arguments
$args_list = @($Script)

if ($Date) {
    $args_list += '--date'
    $args_list += $Date
}

if ($Force) {
    $args_list += '--force'
}

if ($DryRun) {
    $args_list += '--dry-run'
}

if ($Verbose) {
    $args_list += '--verbose'
}

# Log execution
$LogDir = Join-Path $Root 'logs'
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$DateStr = if ($Date) { $Date } else { Get-Date -Format "yyyy-MM-dd" }
$LogFile = Join-Path $LogDir "eod_weekday_$DateStr.log"

Write-Host ""
Write-Host "=== EOD Weekday Master Update ===" -ForegroundColor Cyan
Write-Host "Date: $DateStr" -ForegroundColor Gray
Write-Host "Log:  $LogFile" -ForegroundColor Gray
Write-Host ""

# Run script and capture output
& $VenvPython @args_list | Tee-Object -FilePath $LogFile

$ExitCode = $LASTEXITCODE

# Show result
Write-Host ""
if ($ExitCode -eq 0) {
    Write-Host "✓ EOD update completed successfully" -ForegroundColor Green
    Write-Host "  Check report: data\weekday_master\_eod_reports\$DateStr`_*_eod.json" -ForegroundColor Gray
} else {
    Write-Host "✗ EOD update failed (exit code: $ExitCode)" -ForegroundColor Red
    Write-Host "  Check log: $LogFile" -ForegroundColor Yellow
}
Write-Host ""

exit $ExitCode
