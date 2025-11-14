param(
    [switch]$WhatIf
)

# Purge Python bytecode caches across the workspace
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspace = Split-Path -Parent $root
Write-Host "Purging __pycache__ and *.pyc under: $workspace" -ForegroundColor Cyan

# Remove __pycache__ directories
Get-ChildItem -Path $workspace -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object {
        try {
            if ($WhatIf) {
                Write-Host "[WhatIf] Would remove dir: $($_.FullName)" -ForegroundColor Yellow
            } else {
                Write-Host "Removing dir: $($_.FullName)" -ForegroundColor Yellow
                Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
            }
        } catch {
            Write-Host "Skip dir (error): $($_.Exception.Message)" -ForegroundColor DarkGray
        }
    }

# Remove stray .pyc files
Get-ChildItem -Path $workspace -Recurse -File -Include *.pyc -ErrorAction SilentlyContinue |
    ForEach-Object {
        try {
            if ($WhatIf) {
                Write-Host "[WhatIf] Would remove file: $($_.FullName)" -ForegroundColor Yellow
            } else {
                Write-Host "Removing file: $($_.FullName)" -ForegroundColor Yellow
                Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
            }
        } catch {
            Write-Host "Skip file (error): $($_.Exception.Message)" -ForegroundColor DarkGray
        }
    }

Write-Host "Purge complete." -ForegroundColor Green
