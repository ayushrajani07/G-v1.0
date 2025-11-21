Param(
  [string]$Root = 'grafana/dashboards'
)

function Needs-Patch($text){ return $text -like '*127.0.0.1:9500/api/live_csv*' }

$files = Get-ChildItem -Path $Root -Recurse -Filter *.json
$patched = @()

foreach($f in $files){
  $raw = Get-Content -Raw -Path $f.FullName
  if(-not (Needs-Patch $raw)){ continue }

  $orig = $raw
  # 1. Port swap
  $raw = $raw -replace '127.0.0.1:9500','127.0.0.1:9510'

  # 2. Normalize include_vol -> include_volume
  $raw = $raw -replace 'include_vol=','include_volume='

  # 3. Remove explicit triple false and replace with full include set (plain & encoded)
  $raw = $raw -replace 'include_volume=false&include_oi=false&include_pcr=false','include_index=1&include_oi=1&include_volume=1&include_pcr=1'
  $raw = $raw -replace 'include_volume=false\\u0026include_oi=false\\u0026include_pcr=false','include_index=1\\u0026include_oi=1\\u0026include_volume=1\\u0026include_pcr=1'

  # 4. Regex patch each live_csv URL to ensure flags exist (avoid duplicates)
  $pattern = 'http://127\.0\.0\.1:9510/api/live_csv\?[^"\n]+'
  $matches = [System.Text.RegularExpressions.Regex]::Matches($raw,$pattern)
  foreach($m in $matches){
    $url = $m.Value
    if($url -notmatch 'include_index=1' -or $url -notmatch 'include_oi=1' -or $url -notmatch 'include_volume=1' -or $url -notmatch 'include_pcr=1'){
      # Remove any older false flags patterns leftover
      $new = $url -replace 'include_volume=false','' -replace 'include_oi=false','' -replace 'include_pcr=false',''
      # Avoid double ampersands from removals
      $new = $new -replace '&&','&' -replace '\?&','?'
      # Append mandatory flags if missing one or more
      $needs = @()
      if($new -notmatch 'include_index=1'){ $needs += 'include_index=1' }
      if($new -notmatch 'include_oi=1'){ $needs += 'include_oi=1' }
      if($new -notmatch 'include_volume=1'){ $needs += 'include_volume=1' }
      if($new -notmatch 'include_pcr=1'){ $needs += 'include_pcr=1' }
      if($needs.Count -gt 0){
        $join = ($needs -join '&')
        if($new.Contains('?')){ $new = "$new&$join" } else { $new = "$new?$join" }
      }
      $raw = $raw.Replace($url,$new)
    }
  }

  if($raw -ne $orig){
    $raw | Set-Content -Path $f.FullName -Encoding UTF8
    $patched += $f.FullName
  }
}

Write-Host "Patched files:" -ForegroundColor Cyan
$patched | ForEach-Object { Write-Host $_ }
Write-Host "Total patched: $($patched.Count)" -ForegroundColor Green
if($patched.Count -eq 0){ Write-Host 'No files required patching' -ForegroundColor Yellow }
