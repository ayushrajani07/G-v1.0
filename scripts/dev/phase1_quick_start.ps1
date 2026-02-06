# Phase 1 quick start: enable index-parallelism and CSVIO fast-path
# Usage: Run from repo root in PowerShell

param(
    [int] $Workers = 0,
    [int] $FlushMs = 500,
    [int] $Batch = 2000,
    [string] $MetricsHost = "127.0.0.1",
    [int] $MetricsPort = 9118,
    [float] $LingerSeconds = 10.0,
    [string] $ConfigPath = "config/g6_config.json"
)

# Resolve python
$py = (Get-Command python).Source

# Derive sensible default worker count from CPUs if not provided
if ($Workers -le 0) {
    try {
        $cpu = [Environment]::ProcessorCount
        if ($cpu -lt 1) { $cpu = 4 }
        $Workers = $cpu
    } catch {
        $Workers = 4
    }
}

# Set CSVIO fast-path environment toggles
$env:G6_CSVIO_BACKEND = 'filesystem'
$env:G6_CSVIO_FLUSH_MS = [string]$FlushMs
$env:G6_CSVIO_BATCH = [string]$Batch

# Optional: allow providerless cycles to validate metrics if providers are missing
if (-not $env:G6_ALLOW_PROVIDERLESS_CYCLES) { $env:G6_ALLOW_PROVIDERLESS_CYCLES = '1' }

# Start orchestrator loop with parallel indices and metrics overrides
& $py scripts/run_orchestrator_loop.py `
    --config $ConfigPath `
    --parallel `
    --parallel-workers $Workers `
    --parallel-stagger-ms 0 `
    --csvio-fastpath `
    --csvio-flush-ms $FlushMs `
    --csvio-batch $Batch `
    --metrics-host $MetricsHost `
    --metrics-port $MetricsPort `
    --linger-seconds $LingerSeconds

exit $LASTEXITCODE
