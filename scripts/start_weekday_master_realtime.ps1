# Start Weekday Master Real-time Builder
# Continuously updates weekday masters during market hours

param(
    [int]$Interval = 60,  # Update every 60 seconds
    [switch]$MarketHoursOnly,  # Only run during market hours (9:15 AM - 3:30 PM IST)
    [switch]$Verbose
)

$Root = $PSScriptRoot | Split-Path -Parent
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$Script = Join-Path $Root 'scripts\weekday_master_realtime.py'

# Check if venv Python exists
if (-not (Test-Path $VenvPython)) {
    Write-Host "ERROR: Virtual environment not found at $VenvPython" -ForegroundColor Red
    Write-Host "Please run: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

# Check if script exists
if (-not (Test-Path $Script)) {
    Write-Host "ERROR: Script not found at $Script" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Starting Weekday Master Real-time Builder ===" -ForegroundColor Cyan
Write-Host "Interval:         $Interval seconds" -ForegroundColor Gray
Write-Host "Market hours only: $MarketHoursOnly" -ForegroundColor Gray
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

# Build arguments
$args_list = @($Script, '--interval', $Interval)

if ($MarketHoursOnly) {
    $args_list += '--market-hours-only'
}

if ($Verbose) {
    $args_list += '--verbose'
}

# Run the script
& $VenvPython @args_list
