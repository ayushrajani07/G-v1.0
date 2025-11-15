# Windows 11 Post-Reinstall Fixes
# Fixes: Power settings resetting + NVIDIA GPU stuck in power save mode
# Run as Administrator

Write-Host "======================================================================"
Write-Host "        Windows 11 Post-Reinstall Power & GPU Fixes"
Write-Host "======================================================================"
Write-Host ""

# Check admin privileges
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[ERROR] This script requires Administrator privileges" -ForegroundColor Red
    Write-Host ""
    Write-Host "Right-click this script and select 'Run as Administrator'" -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

Write-Host "[OK] Running with Administrator privileges" -ForegroundColor Green
Write-Host ""

# Fix 1: Set High Performance Power Plan
Write-Host "[1/8] Setting High Performance Power Plan..." -ForegroundColor Cyan
try {
    powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c 2>&1 | Out-Null
    $activePlan = powercfg /getactivescheme
    Write-Host "      [OK] Power plan: $activePlan" -ForegroundColor Green
} catch {
    Write-Host "      [WARNING] Could not set power plan" -ForegroundColor Yellow
}

# Fix 2: Disable Fast Startup
Write-Host "[2/8] Disabling Fast Startup (prevents setting resets)..." -ForegroundColor Cyan
try {
    reg add "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power" /v HiberbootEnabled /t REG_DWORD /d 0 /f 2>&1 | Out-Null
    Write-Host "      [OK] Fast Startup disabled" -ForegroundColor Green
} catch {
    Write-Host "      [WARNING] Could not disable Fast Startup" -ForegroundColor Yellow
}

# Fix 3: Disable Power Throttling
Write-Host "[3/8] Disabling Power Throttling..." -ForegroundColor Cyan
try {
    New-Item -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling" -Force -ErrorAction SilentlyContinue | Out-Null
    reg add "HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling" /v PowerThrottlingOff /t REG_DWORD /d 1 /f 2>&1 | Out-Null
    Write-Host "      [OK] Power Throttling disabled" -ForegroundColor Green
} catch {
    Write-Host "      [WARNING] Could not disable Power Throttling" -ForegroundColor Yellow
}

# Fix 4: Configure PCI Express (GPU) Power Management
Write-Host "[4/8] Configuring PCI Express (GPU) power management..." -ForegroundColor Cyan
try {
    powercfg /setacvalueindex scheme_current sub_pciexpress aspm 0 2>&1 | Out-Null
    powercfg /setdcvalueindex scheme_current sub_pciexpress aspm 0 2>&1 | Out-Null
    powercfg /setactive scheme_current 2>&1 | Out-Null
    Write-Host "      [OK] PCI Express link state power management disabled" -ForegroundColor Green
} catch {
    Write-Host "      [WARNING] Could not configure PCI Express" -ForegroundColor Yellow
}

# Fix 5: Set Sleep Timeouts
Write-Host "[5/8] Setting sleep timeouts..." -ForegroundColor Cyan
try {
    powercfg /change /standby-timeout-ac 0 2>&1 | Out-Null
    powercfg /change /monitor-timeout-ac 30 2>&1 | Out-Null
    powercfg /change /standby-timeout-dc 15 2>&1 | Out-Null
    powercfg /change /monitor-timeout-dc 10 2>&1 | Out-Null
    Write-Host "      [OK] AC: Never sleep, 30 min display timeout" -ForegroundColor Green
    Write-Host "      [OK] Battery: 15 min sleep, 10 min display timeout" -ForegroundColor Green
} catch {
    Write-Host "      [WARNING] Could not set sleep timeouts" -ForegroundColor Yellow
}

# Fix 6: Disable USB Selective Suspend
Write-Host "[6/8] Disabling USB selective suspend..." -ForegroundColor Cyan
try {
    powercfg /setacvalueindex scheme_current 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0 2>&1 | Out-Null
    powercfg /setactive scheme_current 2>&1 | Out-Null
    Write-Host "      [OK] USB selective suspend disabled" -ForegroundColor Green
} catch {
    Write-Host "      [WARNING] Could not disable USB selective suspend" -ForegroundColor Yellow
}

# Fix 7: Configure GPU Preferences for Python
Write-Host "[7/8] Configuring GPU preferences for Python..." -ForegroundColor Cyan
$pythonPaths = @(
    "C:\Windows\System32\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python39\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python310\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python311\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Program Files\Python39\python.exe",
    "C:\Program Files\Python310\python.exe",
    "C:\Program Files\Python311\python.exe",
    "C:\Program Files\Python312\python.exe"
)

$regPath = "HKCU:\Software\Microsoft\DirectX\UserGpuPreferences"
if (-not (Test-Path $regPath)) {
    New-Item -Path $regPath -Force | Out-Null
}

$pythonFound = 0
foreach ($path in $pythonPaths) {
    if (Test-Path $path) {
        try {
            Set-ItemProperty -Path $regPath -Name $path -Value "GpuPreference=2;" -Force
            Write-Host "      [OK] GPU preference set: $path" -ForegroundColor Green
            $pythonFound++
        } catch {
            Write-Host "      [WARNING] Could not set GPU preference for: $path" -ForegroundColor Yellow
        }
    }
}

if ($pythonFound -eq 0) {
    Write-Host "      [WARNING] No Python installations found in standard locations" -ForegroundColor Yellow
    Write-Host "      [INFO] You can manually set GPU preference in Windows Settings" -ForegroundColor Cyan
}

# Fix 8: Processor Power Management
Write-Host "[8/8] Configuring processor power management..." -ForegroundColor Cyan
try {
    # Set minimum processor state to 100% (no throttling)
    powercfg /setacvalueindex scheme_current sub_processor PROCTHROTTLEMIN 100 2>&1 | Out-Null
    # Set maximum processor state to 100%
    powercfg /setacvalueindex scheme_current sub_processor PROCTHROTTLEMAX 100 2>&1 | Out-Null
    powercfg /setactive scheme_current 2>&1 | Out-Null
    Write-Host "      [OK] Processor set to maximum performance (no throttling)" -ForegroundColor Green
} catch {
    Write-Host "      [WARNING] Could not configure processor power management" -ForegroundColor Yellow
}

# Summary
Write-Host ""
Write-Host "======================================================================"
Write-Host "                    Fixes Applied Successfully!" -ForegroundColor Green
Write-Host "======================================================================"
Write-Host ""

# Check NVIDIA GPU
Write-Host "Checking NVIDIA GPU status..." -ForegroundColor Cyan
try {
    $gpuInfo = nvidia-smi --query-gpu=name,driver_version,power.draw --format=csv,noheader 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] GPU detected: $gpuInfo" -ForegroundColor Green
    } else {
        Write-Host "[WARNING] Could not query NVIDIA GPU (nvidia-smi failed)" -ForegroundColor Yellow
        Write-Host "          Make sure NVIDIA drivers are installed" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[WARNING] NVIDIA drivers may not be installed" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "======================================================================"
Write-Host "                         NEXT STEPS" -ForegroundColor Yellow
Write-Host "======================================================================"
Write-Host ""
Write-Host "1. RESTART YOUR PC (Required!)" -ForegroundColor Cyan
Write-Host "   - Changes take effect after reboot" -ForegroundColor Gray
Write-Host ""
Write-Host "2. After restart, open NVIDIA Control Panel:" -ForegroundColor Cyan
Write-Host "   - Right-click desktop -> NVIDIA Control Panel" -ForegroundColor Gray
Write-Host "   - Go to 'Manage 3D Settings' -> 'Global Settings'" -ForegroundColor Gray
Write-Host "   - Set 'Preferred graphics processor' to:" -ForegroundColor Gray
Write-Host "     'High-performance NVIDIA processor'" -ForegroundColor Green
Write-Host "   - Click Apply" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Verify fixes worked:" -ForegroundColor Cyan
Write-Host "   - Run: powershell -File scripts\diagnose_power_issues.ps1" -ForegroundColor Gray
Write-Host "   - Test GPU: python scripts\ml\benchmark_gpu.py" -ForegroundColor Gray
Write-Host ""
Write-Host "4. Optional - Windows Graphics Settings:" -ForegroundColor Cyan
Write-Host "   - Press Win+I -> System -> Display -> Graphics" -ForegroundColor Gray
Write-Host "   - Add Python.exe -> Set to 'High performance'" -ForegroundColor Gray
Write-Host ""
Write-Host "======================================================================"
Write-Host ""

# Offer to restart
Write-Host "Would you like to restart now? (Y/N): " -ForegroundColor Yellow -NoNewline
$response = Read-Host

if ($response -eq 'Y' -or $response -eq 'y') {
    Write-Host ""
    Write-Host "Restarting in 10 seconds..." -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to cancel" -ForegroundColor Gray
    Start-Sleep -Seconds 3
    shutdown /r /t 10 /c "Restarting to apply power and GPU fixes"
} else {
    Write-Host ""
    Write-Host "Please restart manually when ready" -ForegroundColor Yellow
    Write-Host ""
    pause
}
