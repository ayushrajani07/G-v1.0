# Setup EOD Weekday Master - Windows Task Scheduler
# Creates a scheduled task to run EOD updates daily at 4:00 PM IST

param(
    [string]$Time = "16:00",         # Time to run (HH:MM format, 24-hour)
    [string]$TaskName = "G6_EOD_Weekday_Master",
    [switch]$Uninstall,              # Remove the scheduled task
    [switch]$ShowStatus              # Show current task status
)

$Root = $PSScriptRoot | Split-Path -Parent
$ScriptPath = Join-Path $Root 'scripts\eod_weekday_master.ps1'

# Check if running as administrator
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $IsAdmin) {
    Write-Host ""
    Write-Host "WARNING: Not running as Administrator" -ForegroundColor Yellow
    Write-Host "Task creation may fail. Run PowerShell as Administrator if needed." -ForegroundColor Yellow
    Write-Host ""
}

# Show status
if ($ShowStatus) {
    Write-Host ""
    Write-Host "=== EOD Weekday Master - Task Status ===" -ForegroundColor Cyan
    Write-Host ""
    
    try {
        $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        
        if ($Task) {
            Write-Host "Task Name:   $TaskName" -ForegroundColor Green
            Write-Host "State:       $($Task.State)" -ForegroundColor White
            Write-Host "Last Run:    $($Task | Get-ScheduledTaskInfo | Select-Object -ExpandProperty LastRunTime)" -ForegroundColor Gray
            Write-Host "Next Run:    $($Task | Get-ScheduledTaskInfo | Select-Object -ExpandProperty NextRunTime)" -ForegroundColor Gray
            Write-Host "Last Result: $($Task | Get-ScheduledTaskInfo | Select-Object -ExpandProperty LastTaskResult)" -ForegroundColor Gray
            
            Write-Host ""
            Write-Host "Trigger:" -ForegroundColor Yellow
            $Task.Triggers | ForEach-Object {
                Write-Host "  Daily at $($_.StartBoundary.Substring(11, 5))" -ForegroundColor White
                Write-Host "  Days: $($_.DaysOfWeek -join ', ')" -ForegroundColor Gray
            }
            
            Write-Host ""
            Write-Host "Action:" -ForegroundColor Yellow
            $Task.Actions | ForEach-Object {
                Write-Host "  $($_.Execute) $($_.Arguments)" -ForegroundColor White
            }
        } else {
            Write-Host "Task not found: $TaskName" -ForegroundColor Red
            Write-Host "Run without -ShowStatus to create it" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Error checking task status: $_" -ForegroundColor Red
    }
    
    Write-Host ""
    exit 0
}

# Uninstall
if ($Uninstall) {
    Write-Host ""
    Write-Host "=== Removing EOD Weekday Master Task ===" -ForegroundColor Cyan
    Write-Host ""
    
    try {
        $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        
        if ($Task) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "✓ Task removed: $TaskName" -ForegroundColor Green
        } else {
            Write-Host "Task not found: $TaskName" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Error removing task: $_" -ForegroundColor Red
        exit 1
    }
    
    Write-Host ""
    exit 0
}

# Create/Update task
Write-Host ""
Write-Host "=== Setting up EOD Weekday Master Task ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Task Name:    $TaskName" -ForegroundColor White
Write-Host "Schedule:     Daily at $Time" -ForegroundColor White
Write-Host "Days:         Monday-Friday (weekdays)" -ForegroundColor White
Write-Host "Script:       $ScriptPath" -ForegroundColor White
Write-Host "Working Dir:  $Root" -ForegroundColor White
Write-Host ""

# Check if script exists
if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: Script not found: $ScriptPath" -ForegroundColor Red
    exit 1
}

try {
    # Remove existing task if present
    $ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($ExistingTask) {
        Write-Host "Removing existing task..." -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    
    # Create action
    $Action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
        -WorkingDirectory $Root
    
    # Create trigger (daily at specified time, weekdays only)
    $Trigger = New-ScheduledTaskTrigger `
        -Daily `
        -At $Time `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday
    
    # Create settings
    $Settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -DontStopIfGoingOnBatteries `
        -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    
    # Register task
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "G6 End-of-Day Weekday Master Update - Runs daily at $Time to update weekday master overlays" `
        -ErrorAction Stop | Out-Null
    
    Write-Host ""
    Write-Host "✓ Task created successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "The task will run automatically at $Time on weekdays." -ForegroundColor White
    Write-Host ""
    Write-Host "Management:" -ForegroundColor Yellow
    Write-Host "  View status:  .\scripts\setup_eod_schedule.ps1 -ShowStatus" -ForegroundColor Gray
    Write-Host "  Run manually: .\scripts\eod_weekday_master.ps1" -ForegroundColor Gray
    Write-Host "  Uninstall:    .\scripts\setup_eod_schedule.ps1 -Uninstall" -ForegroundColor Gray
    Write-Host "  Task Manager: Open Task Scheduler (taskschd.msc) → Task Scheduler Library → $TaskName" -ForegroundColor Gray
    Write-Host ""
    
    # Show next run time
    $Task = Get-ScheduledTask -TaskName $TaskName
    $NextRun = $Task | Get-ScheduledTaskInfo | Select-Object -ExpandProperty NextRunTime
    Write-Host "Next scheduled run: $NextRun" -ForegroundColor Cyan
    Write-Host ""
    
} catch {
    Write-Host ""
    Write-Host "ERROR: Failed to create scheduled task" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Try running PowerShell as Administrator" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

exit 0
