# Weekday Master Quick Start
# Initializes weekday master system and provides guidance

param(
    [switch]$GenerateAll,      # Generate from all historical data
    [switch]$GenerateLast30,   # Generate from last 30 days only
    [switch]$StartRealtime,    # Start real-time builder after generation
    [switch]$Help
)

$Root = $PSScriptRoot | Split-Path -Parent
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$BatchScript = Join-Path $Root 'scripts\weekday_master_batch.py'
$RealtimeScript = Join-Path $Root 'scripts\start_weekday_master_realtime.ps1'
$WeekdayMasterDir = Join-Path $Root 'data\weekday_master'

function Show-Help {
    Write-Host ""
    Write-Host "=== Weekday Master Quick Start ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\scripts\weekday_master_quickstart.ps1 -GenerateAll        # Generate from all historical data"
    Write-Host "  .\scripts\weekday_master_quickstart.ps1 -GenerateLast30     # Generate from last 30 days"
    Write-Host "  .\scripts\weekday_master_quickstart.ps1 -GenerateAll -StartRealtime  # Generate + start real-time"
    Write-Host ""
    Write-Host "What it does:" -ForegroundColor Yellow
    Write-Host "  1. Checks if weekday_master directory exists"
    Write-Host "  2. Scans data/g6_data/ for available CSV data"
    Write-Host "  3. Generates weekday master files"
    Write-Host "  4. Optionally starts real-time builder"
    Write-Host ""
    Write-Host "For detailed documentation: docs\WEEKDAY_MASTER_GUIDE.md" -ForegroundColor Green
    Write-Host ""
}

if ($Help -or (-not $GenerateAll -and -not $GenerateLast30)) {
    Show-Help
    exit 0
}

# Check prerequisites
Write-Host ""
Write-Host "=== Weekday Master Quick Start ===" -ForegroundColor Cyan
Write-Host ""

# Check venv
if (-not (Test-Path $VenvPython)) {
    Write-Host "ERROR: Virtual environment not found" -ForegroundColor Red
    Write-Host "Please run: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}
Write-Host " Python venv found" -ForegroundColor Green

# Check if weekday_master exists
$MasterExists = Test-Path $WeekdayMasterDir
if ($MasterExists) {
    Write-Host " weekday_master directory exists" -ForegroundColor Yellow
    $FileCount = (Get-ChildItem -Path $WeekdayMasterDir -Recurse -Filter "*.csv" -ErrorAction SilentlyContinue | Measure-Object).Count
    Write-Host "   Contains $FileCount CSV files" -ForegroundColor Gray
    Write-Host ""
    $Confirm = Read-Host "Regenerate weekday masters? (y/N)"
    if ($Confirm -ne 'y' -and $Confirm -ne 'Y') {
        Write-Host "Cancelled by user" -ForegroundColor Yellow
        exit 0
    }
} else {
    Write-Host " weekday_master directory will be created" -ForegroundColor Cyan
}

# Check for CSV data
Write-Host ""
Write-Host "Checking for CSV data..." -ForegroundColor Cyan
$G6DataDir = Join-Path $Root 'data\g6_data'
if (-not (Test-Path $G6DataDir)) {
    Write-Host "ERROR: No data/g6_data directory found" -ForegroundColor Red
    Write-Host "Please ensure CSV collectors have run and created data" -ForegroundColor Yellow
    exit 1
}

$CsvFiles = Get-ChildItem -Path $G6DataDir -Recurse -Filter "*.csv" -ErrorAction SilentlyContinue
$CsvCount = ($CsvFiles | Measure-Object).Count

if ($CsvCount -eq 0) {
    Write-Host "ERROR: No CSV files found in data/g6_data/" -ForegroundColor Red
    Write-Host "Please run collectors first to generate data" -ForegroundColor Yellow
    exit 1
}

Write-Host " Found $CsvCount CSV files" -ForegroundColor Green

# Find date range
$DateFiles = $CsvFiles | Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}\.csv$' }
if ($DateFiles) {
    $Dates = $DateFiles | ForEach-Object { 
        if ($_.Name -match '^(\d{4}-\d{2}-\d{2})\.csv$') {
            [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd', $null)
        }
    } | Where-Object { $_ -ne $null } | Sort-Object
    
    if ($Dates) {
        $FirstDate = ($Dates | Select-Object -First 1).ToString('yyyy-MM-dd')
        $LastDate = ($Dates | Select-Object -Last 1).ToString('yyyy-MM-dd')
        $DateCount = $Dates.Count
        Write-Host "   Date range: $FirstDate to $LastDate ($DateCount days)" -ForegroundColor Gray
    }
}

# Run batch generator
Write-Host ""
Write-Host "=== Generating Weekday Masters ===" -ForegroundColor Cyan
Write-Host ""

if ($GenerateAll) {
    Write-Host "Processing ALL available data..." -ForegroundColor Yellow
    $args_list = @($BatchScript, '--all', '--verbose')
} elseif ($GenerateLast30) {
    Write-Host "Processing last 30 days..." -ForegroundColor Yellow
    $args_list = @($BatchScript, '--days', '30', '--verbose')
}

Write-Host "Command: python $BatchScript" -ForegroundColor Gray
Write-Host "This may take several minutes..." -ForegroundColor Gray
Write-Host ""

$StartTime = Get-Date
& $VenvPython @args_list

$ExitCode = $LASTEXITCODE
$Duration = (Get-Date) - $StartTime

Write-Host ""
if ($ExitCode -eq 0) {
    Write-Host "=== Generation Complete ===" -ForegroundColor Green
    Write-Host "Duration: $($Duration.ToString('mm\:ss'))" -ForegroundColor Gray
    
    # Show results
    if (Test-Path $WeekdayMasterDir) {
        $NewFileCount = (Get-ChildItem -Path $WeekdayMasterDir -Recurse -Filter "*.csv" -ErrorAction SilentlyContinue | Measure-Object).Count
        Write-Host "Created/updated $NewFileCount weekday master files" -ForegroundColor Green
        
        # Show sample structure
        Write-Host ""
        Write-Host "Directory structure:" -ForegroundColor Yellow
        Get-ChildItem -Path $WeekdayMasterDir -Directory | Select-Object -First 2 | ForEach-Object {
            Write-Host "  $($_.Name)/" -ForegroundColor Cyan
            Get-ChildItem -Path $_.FullName -Directory | Select-Object -First 1 | ForEach-Object {
                Write-Host "    $($_.Name)/" -ForegroundColor Gray
                Get-ChildItem -Path $_.FullName -Directory | Select-Object -First 1 | ForEach-Object {
                    Write-Host "      $($_.Name)/" -ForegroundColor DarkGray
                    Get-ChildItem -Path $_.FullName -Filter "*.csv" | Select-Object -First 3 | ForEach-Object {
                        Write-Host "        $($_.Name)" -ForegroundColor DarkGray
                    }
                }
            }
        }
    }
    
    # Check quality reports
    $QualityDir = Join-Path $WeekdayMasterDir '_quality_reports'
    if (Test-Path $QualityDir) {
        $ReportCount = (Get-ChildItem -Path $QualityDir -Filter "*.json" -ErrorAction SilentlyContinue | Measure-Object).Count
        if ($ReportCount -gt 0) {
            Write-Host ""
            Write-Host "Quality reports: $QualityDir ($ReportCount reports)" -ForegroundColor Cyan
        }
    }
    
} else {
    Write-Host "=== Generation Failed ===" -ForegroundColor Red
    Write-Host "Exit code: $ExitCode" -ForegroundColor Red
    Write-Host "Check logs above for errors" -ForegroundColor Yellow
    exit $ExitCode
}

# Start real-time builder if requested
if ($StartRealtime) {
    Write-Host ""
    Write-Host "=== Starting Real-time Builder ===" -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
    Write-Host ""
    Start-Sleep -Seconds 2
    
    & $RealtimeScript -MarketHoursOnly -Interval 60
}

Write-Host ""
Write-Host "=== Next Steps ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. View documentation:  docs\WEEKDAY_MASTER_GUIDE.md" -ForegroundColor White
Write-Host "2. Start real-time builder:" -ForegroundColor White
Write-Host "   .\scripts\start_weekday_master_realtime.ps1 -MarketHoursOnly" -ForegroundColor Gray
Write-Host "3. Start overlay exporter (for Prometheus):" -ForegroundColor White
Write-Host "   python scripts\overlay_exporter.py" -ForegroundColor Gray
Write-Host "4. Check quality reports:" -ForegroundColor White
Write-Host "   cat data\weekday_master\_quality_reports\<date>_quality.json" -ForegroundColor Gray
Write-Host ""
