param(
  [string]$Version = '11.2.0',
  [string]$DestRoot = 'C:\Grafana',
  [switch]$StartAfter,
  [switch]$Anonymous,
  [switch]$OpenBrowser
)

$ErrorActionPreference = 'Continue'

function New-EnsuredDirectory { param([string]$Path) if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null } }

try {
  New-EnsuredDirectory -Path $DestRoot
  $zipName = "grafana-$Version.windows-amd64.zip"
  $url = "https://dl.grafana.com/oss/release/$zipName"
  $zipPath = Join-Path $DestRoot $zipName
  Write-Host ("Downloading Grafana {0}..." -f $Version) -ForegroundColor Cyan
  Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zipPath -TimeoutSec 120

  $extractDir = Join-Path $DestRoot ("grafana-$Version")
  if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
  Write-Host ("Extracting to {0}..." -f $extractDir) -ForegroundColor Cyan
  Expand-Archive -Force -Path $zipPath -DestinationPath $DestRoot
  if (-not (Test-Path $extractDir)) {
    # Some archives may expand into a nested folder name; try to locate
    $cand = Get-ChildItem -Path $DestRoot -Directory | Where-Object { $_.Name -like "grafana-*" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($cand) { $extractDir = $cand.FullName }
  }
  if (-not (Test-Path (Join-Path (Join-Path $extractDir 'bin') 'grafana-server.exe'))) {
    Write-Host 'Extraction completed but grafana-server.exe not found.' -ForegroundColor Red
    exit 1
  }
  # Set env for auto_stack to pick this install first
  [Environment]::SetEnvironmentVariable('G6_GRAFANA_ROOT', $extractDir)
  Write-Host ("G6_GRAFANA_ROOT set to {0}" -f $extractDir) -ForegroundColor Green

  if ($StartAfter) {
    $script = Join-Path (Split-Path $MyInvocation.MyCommand.Path -Parent) 'start_grafana_only.ps1'
    if ($Anonymous -and $OpenBrowser) {
      & $script -OpenBrowser -Anonymous
    } elseif ($Anonymous) {
      & $script -Anonymous
    } elseif ($OpenBrowser) {
      & $script -OpenBrowser
    } else {
      & $script
    }
    exit $LASTEXITCODE
  }
  exit 0
} catch {
  try { Write-Host ("get_portable_grafana.ps1 failed: {0}" -f $_.Exception.Message) -ForegroundColor Red } catch {}
  exit 1
}
