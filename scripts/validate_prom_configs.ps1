Param(
  [string]$PromConfigPath = "prometheus.yml",
  [string[]]$RuleFiles = @(
    "prometheus_rules_ml.yml",
    "prometheus_rules_ml_autotune.yml",
    "prometheus_rules_ml_drift.yml",
    "prometheus_rules.yml"
  ),
  [string]$AlertmanagerPath = "alertmanager.yml"
)

Write-Host "Validating Prometheus config: $PromConfigPath"
if (!(Test-Path $PromConfigPath)) { Write-Error "Missing $PromConfigPath"; exit 1 }

Write-Host "Validating rule files..."
foreach ($rf in $RuleFiles) {
  if (!(Test-Path $rf)) { Write-Host "Skipping missing rule file: $rf"; continue }
  try {
    $yaml = Get-Content $rf -Raw
    if ([string]::IsNullOrWhiteSpace($yaml)) { throw "Empty file: $rf" }
  } catch {
    Write-Error "Failed to read $rf: $_"; exit 1
  }
}

Write-Host "Validating Alertmanager config: $AlertmanagerPath"
if (!(Test-Path $AlertmanagerPath)) { Write-Error "Missing $AlertmanagerPath"; exit 1 }

Write-Host "Basic validation passed. For full linting, run promtool if available."
Write-Host "Example:" -ForegroundColor Yellow
Write-Host "  promtool check config $PromConfigPath" -ForegroundColor Yellow
Write-Host "  promtool check rules $($RuleFiles -join ' ')" -ForegroundColor Yellow