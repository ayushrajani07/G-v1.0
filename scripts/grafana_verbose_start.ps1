param(
  [int]$Port = 3000,
  [switch]$Anonymous,
  [string]$Root,
  [switch]$Attach
)

$ErrorActionPreference = 'Continue'

function New-EnsuredDirectory { param([string]$Path) if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null } }

try {
  # Ensure only one Grafana instance is listening on the desired port
  try {
    # Stop Windows-installed grafana service if it is running on same port
    $svc = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'grafana' }
    if ($svc -and $svc.Status -eq 'Running') {
      try { Stop-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue } catch {}
      Start-Sleep -Seconds 2
    }
  } catch {}
  try {
    # Kill any stray grafana processes
    Get-Process -Name 'grafana','grafana-server' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  } catch {}
  try {
    # Free the target port if occupied
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
  } catch {}
  # Resolve Grafana home/exe: prefer -Root, then env var, then C:\Grafana portable, then Program Files
  if (-not $Root -or -not (Test-Path $Root)) {
    if ($env:G6_GRAFANA_ROOT -and (Test-Path $env:G6_GRAFANA_ROOT)) { $Root = $env:G6_GRAFANA_ROOT }
  }
  if (-not $Root -or -not (Test-Path $Root)) {
    try {
      $candPort = Get-ChildItem -Path 'C:\Grafana' -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'grafana*' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if ($candPort) { $Root = $candPort.FullName }
    } catch {}
  }
  $exe = $null; $gHome = $null
  if ($Root -and (Test-Path $Root)) {
    $candExe = Join-Path (Join-Path $Root 'bin') 'grafana-server.exe'
    if (Test-Path $candExe) { $exe = $candExe; $gHome = $Root }
  }
  if (-not $exe) {
    $pf = 'C:\Program Files'
    $cand = Get-ChildItem -Path $pf -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'grafana*' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($cand) {
      $exe2 = Join-Path (Join-Path $cand.FullName 'bin') 'grafana-server.exe'
      if (Test-Path $exe2) { $exe = $exe2; $gHome = (Split-Path $cand.FullName -Parent) }
    }
    if (-not $exe) {
      # default to standard location
      $exe = 'C:\Program Files\GrafanaLabs\grafana\bin\grafana-server.exe'
      $gHome = 'C:\Program Files\GrafanaLabs\grafana'
    }
  }
  if (-not (Test-Path $exe)) { Write-Host 'grafana-server.exe not found' -ForegroundColor Red; exit 1 }

  $dataRoot = 'C:\GrafanaData'
  New-EnsuredDirectory -Path $dataRoot
  New-EnsuredDirectory -Path (Join-Path $dataRoot 'data')
  New-EnsuredDirectory -Path (Join-Path $dataRoot 'log')
  New-EnsuredDirectory -Path (Join-Path $dataRoot 'plugins')
  # Prefer provisioning from repo if present, else fall back to data root
  $repoRoot = Split-Path $PSScriptRoot -Parent
  $repoProv = Join-Path $repoRoot 'provisioning'
  if (Test-Path $repoProv) {
    [Environment]::SetEnvironmentVariable('GF_PATHS_PROVISIONING', $repoProv)
  } else {
    $dataProv = Join-Path $dataRoot 'provisioning'
    New-EnsuredDirectory -Path $dataProv
    [Environment]::SetEnvironmentVariable('GF_PATHS_PROVISIONING', $dataProv)
  }

  # Set environment for child process
  [Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_PORT',"$Port")
  [Environment]::SetEnvironmentVariable('GF_SERVER_HTTP_ADDR','127.0.0.1')
  [Environment]::SetEnvironmentVariable('GF_PATHS_HOME',$gHome)
  [Environment]::SetEnvironmentVariable('GF_PATHS_DATA', (Join-Path $dataRoot 'data'))
  [Environment]::SetEnvironmentVariable('GF_PATHS_LOGS', (Join-Path $dataRoot 'log'))
  [Environment]::SetEnvironmentVariable('GF_PATHS_PLUGINS', (Join-Path $dataRoot 'plugins'))
  [Environment]::SetEnvironmentVariable('GF_LOG_MODE','console')
  [Environment]::SetEnvironmentVariable('GF_LOG_LEVEL','debug')
  [Environment]::SetEnvironmentVariable('GF_PLUGINS_PREVENT_DOWNLOAD','false')
  [Environment]::SetEnvironmentVariable('GF_INSTALL_PLUGINS','yesoreyeram-infinity-datasource,volkovlabs-form-panel')
  # Allow local/unsigned plugins in offline/dev env
  [Environment]::SetEnvironmentVariable('GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS','yesoreyeram-infinity-datasource,volkovlabs-form-panel')
  # Allow plugins (like Infinity) to reach 127.0.0.1/localhost in dev
  [Environment]::SetEnvironmentVariable('GF_PLUGINS_ALLOW_LOCAL_NETWORKS','true')
  # Ensure Grafana sees the backend URLs for provisioning substitution (standardized ports)
  [Environment]::SetEnvironmentVariable('G6_ANALYTICS_URL','http://127.0.0.1:9500')
  [Environment]::SetEnvironmentVariable('G6_PROM_URL','http://127.0.0.1:9091')
  if ($Anonymous) {
    [Environment]::SetEnvironmentVariable('GF_AUTH_ANONYMOUS_ENABLED','true')
    [Environment]::SetEnvironmentVariable('GF_AUTH_ANONYMOUS_ORG_ROLE','Admin')
    [Environment]::SetEnvironmentVariable('GF_AUTH_DISABLE_LOGIN_FORM','true')
    [Environment]::SetEnvironmentVariable('GF_AUTH_BASIC_ENABLED','false')
    [Environment]::SetEnvironmentVariable('GF_USERS_ALLOW_SIGN_UP','false')
    [Environment]::SetEnvironmentVariable('GF_SECURITY_ALLOW_EMBEDDING','true')
  }

  $out = Join-Path (Join-Path $dataRoot 'log') 'grafana_verbose_stdout.log'
  $err = Join-Path (Join-Path $dataRoot 'log') 'grafana_verbose_stderr.log'
  $argList = "--homepath `"$gHome`""
  if ($Attach) {
    & $exe --homepath "$gHome"
  } else {
    Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $gHome -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Minimized
  }

  Write-Host ("Grafana verbose start requested on :{0}" -f $Port) -ForegroundColor Cyan
  Start-Sleep -Seconds 5
  if (-not $Attach) {
    try {
      $r = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:{0}/api/health" -f $Port) -TimeoutSec 5
      if ($r.StatusCode -eq 200) { Write-Host 'Grafana health OK' -ForegroundColor Green }
      else { Write-Host ("Grafana health: {0}" -f $r.StatusCode) -ForegroundColor Yellow }
    } catch {
      Write-Host 'Grafana not healthy yet; check logs in C:\GrafanaData\log' -ForegroundColor Yellow
    }
  }
  exit 0
} catch {
  try { Write-Host ("grafana_verbose_start.ps1 failed: {0}" -f $_.Exception.Message) -ForegroundColor Red } catch {}
  exit 1
}
