<#!
.SYNOPSIS
  Backup then delete all dashboards from Grafana DB and reload provisioning so file versions are re-imported.
.DESCRIPTION
  1. Fetch all dashboards via /api/search.
  2. For each UID, GET its full JSON and store under backups/<timestamp>/<uid>.json.
  3. Delete the dashboard via /api/dashboards/uid/{uid}.
  4. After all deletions, call provisioning reload endpoint.
  Supports selective mode (only delete dashboards whose UID appears in a file on disk OR those NOT on disk).
.PARAMETER GrafanaUrl
  Base URL of Grafana (default http://127.0.0.1:3002)
.PARAMETER Creds
  Basic auth in user:pass form. (Default admin:admin)
.PARAMETER Mode
  all            -> delete everything returned by /api/search.
  file           -> delete only dashboards whose UID matches a JSON file under grafana/dashboards/**.
  orphan         -> delete only dashboards whose UID has NO matching file under grafana/dashboards/**.
.PARAMETER DryRun
  If set, just report what would be deleted.
.EXAMPLE
  powershell -File scripts/reset_grafana_dashboards.ps1 -Mode all
.EXAMPLE
  powershell -File scripts/reset_grafana_dashboards.ps1 -Mode orphan -DryRun
!>
Param(
  [string]$GrafanaUrl = 'http://127.0.0.1:3002',
  [string]$Creds = 'admin:admin',
  [ValidateSet('all','file','orphan')][string]$Mode = 'all',
  [switch]$DryRun
)

function Get-AuthHeader($creds){
  $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($creds))
  return @{ Authorization = "Basic $b64" }
}

function Get-DashboardUIDsFromFiles($root){
  $uids = @{}
  Get-ChildItem -Path $root -Recurse -Filter *.json | ForEach-Object {
    $content = Get-Content -Raw -Path $_.FullName
    $m = [regex]::Matches($content,'"uid"\s*:\s*"([^"]+)"')
    foreach($x in $m){ $uids[$x.Groups[1].Value] = $true }
  }
  return $uids.Keys
}

$headers = Get-AuthHeader $Creds
$search = Invoke-RestMethod -Uri "$GrafanaUrl/api/search?query=" -Headers $headers -Method Get
if(-not $search){ Write-Host 'No dashboards returned from API.' -ForegroundColor Yellow; exit }

$fileUIDs = Get-DashboardUIDsFromFiles 'grafana/dashboards'
$setFile = [System.Collections.Generic.HashSet[string]]::new($fileUIDs)

# Determine candidates
$candidates = @()
foreach($d in $search){
  $uid = $d.uid
  if([string]::IsNullOrWhiteSpace($uid)){ continue }
  switch($Mode){
    'all'     { $candidates += $d }
    'file'    { if($setFile.Contains($uid)){ $candidates += $d } }
    'orphan'  { if(-not $setFile.Contains($uid)){ $candidates += $d } }
  }
}

Write-Host "Mode: $Mode" -ForegroundColor Cyan
Write-Host "Dashboards found: $($search.Count) | Candidates for deletion: $($candidates.Count)" -ForegroundColor Cyan
if($candidates.Count -eq 0){ Write-Host 'Nothing to delete.' -ForegroundColor Yellow; exit }

$ts = (Get-Date).ToString('yyyyMMdd_HHmmss')
$backupRoot = Join-Path -Path 'grafana' -ChildPath "dashboard_backups_$ts"
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

foreach($d in $candidates){
  $uid = $d.uid; $title = $d.title
  Write-Host "Processing UID=$uid Title=$title" -ForegroundColor Magenta
  # Backup
  try {
    $full = Invoke-RestMethod -Uri "$GrafanaUrl/api/dashboards/uid/$uid" -Headers $headers -Method Get
    $outPath = Join-Path $backupRoot "$uid.json"
    ($full | ConvertTo-Json -Depth 50) | Set-Content -Path $outPath -Encoding UTF8
    Write-Host "  Backup saved -> $outPath" -ForegroundColor DarkGray
  } catch { Write-Host "  Backup failed: $($_.Exception.Message)" -ForegroundColor Red }

  if($DryRun){ Write-Host '  DryRun: skip delete' -ForegroundColor Yellow; continue }
  try {
    Invoke-RestMethod -Uri "$GrafanaUrl/api/dashboards/uid/$uid" -Headers $headers -Method Delete | Out-Null
    Write-Host "  Deleted." -ForegroundColor Green
  } catch { Write-Host "  Delete failed: $($_.Exception.Message)" -ForegroundColor Red }
}

if(-not $DryRun){
  Write-Host 'Triggering provisioning reload...' -ForegroundColor Cyan
  try {
    Invoke-RestMethod -Uri "$GrafanaUrl/api/admin/provisioning/dashboards/reload" -Headers $headers -Method Post | Out-Null
    Write-Host 'Reload requested.' -ForegroundColor Green
  } catch { Write-Host "Reload failed: $($_.Exception.Message)" -ForegroundColor Red }
}

Write-Host "Done. Backups stored at $backupRoot" -ForegroundColor Cyan
