param(
  [int[]]$Ports = @(9090..9100),
  [string]$BindHost = '127.0.0.1'
)

$ErrorActionPreference = 'Continue'

function Invoke-Reload {
  param([string]$Url)
  try {
    $h = [System.Net.Http.HttpClient]::new()
    $h.Timeout = [TimeSpan]::FromSeconds(3)
    $resp = $h.PostAsync($Url, $null).GetAwaiter().GetResult()
    return [pscustomobject]@{ Url=$Url; Code=[int]$resp.StatusCode; Ok=$resp.IsSuccessStatusCode }
  } catch {
    return [pscustomobject]@{ Url=$Url; Code=-1; Ok=$false }
  }
}

$attempts = @()
foreach ($p in $Ports) {
  $url = "http://${BindHost}:$p/-/reload"
  $r = Invoke-Reload -Url $url
  $attempts += $r
  if ($r.Ok -and $r.Code -eq 200) {
    Write-Host ("Reloaded Prometheus config via {0}" -f $url) -ForegroundColor Green
    exit 0
  }
}

Write-Host "No Prometheus instance accepted /-/reload on the scanned ports." -ForegroundColor Yellow
Write-Host "If lifecycle isn't enabled, restart Prometheus using the VS Code task: 'Prometheus: Start only (auto_stack)'." -ForegroundColor DarkYellow
Write-Host ("Attempts: {0}" -f ($attempts | ForEach-Object { "[$($_.Url) code=$($_.Code)]" } | Out-String))
exit 1
