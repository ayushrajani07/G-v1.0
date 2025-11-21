Param(
  [string]$Freeze,      # dashboard file name to freeze
  [switch]$Validate,    # validate all dashboards
  [string]$Folder = 'grafana/dashboards/dashboards_live'
)

function Write-Info($msg){ Write-Host $msg -ForegroundColor Cyan }
function Write-Warn($msg){ Write-Host $msg -ForegroundColor Yellow }
function Write-Err($msg){ Write-Host $msg -ForegroundColor Red }

if (-not (Test-Path $Folder)) { Write-Err "Folder '$Folder' not found"; exit 1 }

$today = Get-Date -Format 'yyyy-MM-dd'

function Freeze-Dashboard($path){
  try {
    $jsonText = Get-Content -Raw -Path $path
    $data = $jsonText | ConvertFrom-Json
    $changed = $false
    if ($data.editable -ne $false){ $data.editable = $false; $changed = $true }
    if (-not $data.PSObject.Properties.Name.Contains('g6_lock')){ $data | Add-Member -NotePropertyName g6_lock -NotePropertyValue $true; $changed = $true } else { $data.g6_lock = $true }
    $tag = "freeze-$today"
    if (-not $data.PSObject.Properties.Name.Contains('version_tag')){ $data | Add-Member -NotePropertyName version_tag -NotePropertyValue $tag; $changed = $true }
    elseif ($data.version_tag -ne $tag){ $data.version_tag = $tag; $changed = $true }
    if ($changed){
      ($data | ConvertTo-Json -Depth 50) | Set-Content -Path $path -Encoding UTF8
      Write-Info "Frozen: $(Split-Path $path -Leaf) -> $tag"
    } else {
      Write-Info "Already frozen: $(Split-Path $path -Leaf)"
    }
  } catch { Write-Err "Freeze failed for $path : $_" }
}

function Validate-Frozen($path){
  $jsonText = Get-Content -Raw -Path $path
  $data = $jsonText | ConvertFrom-Json
  $name = Split-Path $path -Leaf
  $issues = @()
  if ($data.g6_lock -ne $true){ $issues += 'lock-missing' }
  if ($data.editable -ne $false){ $issues += 'editable-not-false' }
  if (-not $data.version_tag){ $issues += 'version_tag-missing' }
  [PSCustomObject]@{file=$name; version=$data.version_tag; locked=$data.g6_lock; editable=$data.editable; issues=($issues -join ',')}
}

if ($Freeze){
  $target = Join-Path $Folder $Freeze
  if (-not (Test-Path $target)){ Write-Err "Dashboard file not found: $target"; exit 2 }
  Freeze-Dashboard $target
}

if ($Validate){
  $files = Get-ChildItem -Path $Folder -Filter '*.json'
  $results = foreach($f in $files){ Validate-Frozen $f.FullName }
  Write-Host "\nFrozen Dashboard Validation:" -ForegroundColor Green
  $results | Format-Table -AutoSize
  $bad = $results | Where-Object { $_.issues }
  if ($bad){ Write-Warn "Validation issues detected:"; $bad | Format-Table -AutoSize; exit 3 }
}
