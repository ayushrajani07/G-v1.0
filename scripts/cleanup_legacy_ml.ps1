param(
    [switch]$Apply,
    [switch]$IncludeModels,
    [switch]$IncludeDocs,
    [switch]$IncludePredictions,
    [string]$BackupDir = ""
)

# Resolve repo root from scripts/ directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
Write-Host "Repo root: $RepoRoot" -ForegroundColor Cyan

function Get-SizeMB([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $sum = 0
    if (Test-Path $Path -PathType Leaf) {
        $sum = (Get-Item $Path).Length
    } else {
        Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object { $sum += $_.Length }
    }
    return [Math]::Round($sum / 1MB, 2)
}

# Build deletion list
$targets = @()
$targets += @{ Label = 'Legacy lib'; Path = Join-Path $RepoRoot 'src/ml_arm'; Type='dir' }
$targets += @{ Label = 'Legacy scripts'; Path = Join-Path $RepoRoot 'scripts/ml'; Type='dir' }
$targets += @{ Label = 'Legacy configs'; Path = Join-Path $RepoRoot 'configs/ml'; Type='dir' }

if ($IncludeDocs) {
    $targets += @{ Label = 'Legacy docs (model matrix)'; Path = Join-Path $RepoRoot 'docs'; Type='glob'; Pattern = 'ML_MODEL_MATRIX*.md' }
}
if ($IncludeModels) {
    $targets += @{ Label = 'Model artifacts (legacy)'; Path = Join-Path $RepoRoot 'models'; Type='glob'; Pattern='*tp_forecast*' }
    $targets += @{ Label = 'Champions mapping'; Path = Join-Path $RepoRoot 'models/champions.json'; Type='leaf' }
}
if ($IncludePredictions) {
    $targets += @{ Label = 'Live predictions CSVs'; Path = Join-Path $RepoRoot 'data/ml/live_predictions'; Type='glob'; Pattern='*.csv' }
}

# Expand globs into concrete paths
$expanded = @()
foreach ($t in $targets) {
    $label = $t.Label
    $path = $t.Path
    $type = $t.Type
    $pattern = $t.Pattern
    if ($type -eq 'glob') {
        if (Test-Path $path) {
            $items = Get-ChildItem -LiteralPath $path -Filter $pattern -Recurse -Force -ErrorAction SilentlyContinue
            foreach ($it in $items) {
                if ($it.PSIsContainer) {
                    $typeResolved = 'dir'
                } else {
                    $typeResolved = 'leaf'
                }
                $expanded += @{ Label=$label; Path=$it.FullName; Type=$typeResolved }
            }
        }
    } elseif ($type -eq 'dir' -or $type -eq 'leaf') {
        if (Test-Path $path) {
            $expanded += @{ Label=$label; Path=$path; Type=$type }
        }
    }
}

if (-not $expanded) {
    Write-Host "Nothing to delete (no legacy items found)." -ForegroundColor Yellow
    return
}

# Group and summarize
Write-Host "Planned removals:" -ForegroundColor Green
$sumMB = 0
$idx = 1
foreach ($e in $expanded) {
    $size = Get-SizeMB $e.Path
    $sumMB += $size
    Write-Host ("[{0}] {1} -> {2} ({3} MB)" -f $idx, $e.Label, $e.Path, $size)
    $idx++
}
Write-Host ("Total size: {0} MB" -f [Math]::Round($sumMB,2)) -ForegroundColor Green

if (-not $Apply) {
    Write-Host "Dry-run (preview). Re-run with -Apply to execute." -ForegroundColor Yellow
    return
}

# Optional backup
$backupRoot = $null
if ($BackupDir -and $BackupDir.Trim() -ne '') {
    try {
        # Ensure the base backup directory exists
        if (-not (Test-Path -LiteralPath $BackupDir)) {
            New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
        }
        $resolvedBackupDir = Resolve-Path -LiteralPath $BackupDir
        $ts = Get-Date -Format 'yyyyMMdd_HHmmss'
        $backupRoot = Join-Path $resolvedBackupDir ("legacy_ml_backup_" + $ts)
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        Write-Host "Backing up to: $backupRoot" -ForegroundColor Cyan
        $i = 1
        foreach ($e in $expanded) {
            $rel = $e.Path.Replace($RepoRoot, '').TrimStart('\/')
            $dest = Join-Path $backupRoot $rel
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
            try {
                if ($e.Type -eq 'dir') {
                    Copy-Item -LiteralPath $e.Path -Destination $dest -Recurse -Force -ErrorAction Continue
                } else {
                    Copy-Item -LiteralPath $e.Path -Destination $dest -Force -ErrorAction Continue
                }
            } catch {
                Write-Host "[backup warn] $_" -ForegroundColor DarkYellow
            }
            $i++
        }
    } catch {
        Write-Host "Backup step failed: $_" -ForegroundColor Yellow
    }
}

# Delete
Write-Host "Deleting..." -ForegroundColor Red
foreach ($e in $expanded) {
    try {
        if (Test-Path $e.Path) {
            if ($e.Type -eq 'dir') {
                Remove-Item -LiteralPath $e.Path -Recurse -Force -ErrorAction Continue
            } else {
                Remove-Item -LiteralPath $e.Path -Force -ErrorAction Continue
            }
        }
    } catch {
        Write-Host "[delete warn] $_" -ForegroundColor DarkYellow
    }
}
Write-Host "Cleanup complete." -ForegroundColor Green
