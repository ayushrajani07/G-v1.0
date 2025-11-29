# Network Connectivity Recovery

## Overview

The G6 platform includes automatic internet connectivity monitoring and recovery to handle network interruptions gracefully during collection cycles.

## Features

- **Pre-cycle connectivity checks**: Fast, non-blocking checks (~1s) before each cycle
- **Automatic retry**: Exponential backoff for transient network issues
- **Graceful recovery**: Automatically resumes when connectivity is restored
- **Configurable**: Control via environment variables
- **Minimal dependencies**: Uses socket-level checks (port 53/DNS) for speed

## How It Works

### Normal Operation
1. Before each cycle, check if internet connectivity is available
2. If check passes, proceed with collection cycle
3. Reset failure counter on successful cycle

### Connection Loss
1. Connectivity check fails
2. Log warning and attempt recovery with retries
3. Wait between retries (configurable delay)
4. If connectivity restored, resume normal operation
5. If max retries exceeded, skip cycle but continue loop

### Persistent Failure
- After 3 consecutive cycles with no connectivity recovery
- Exit gracefully with error log
- Prevents infinite loops with no network

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `G6_CONNECTIVITY_CHECK_ENABLED` | `true` | Enable/disable connectivity checking |
| `G6_CONNECTIVITY_CHECK_TIMEOUT` | `3` | Timeout for each check (seconds) |
| `G6_CONNECTIVITY_CHECK_HOSTS` | `8.8.8.8,1.1.1.1` | Comma-separated hosts to check |
| `G6_CONNECTIVITY_MAX_RETRIES` | `3` | Max retry attempts per cycle |
| `G6_CONNECTIVITY_RETRY_DELAY` | `2` | Delay between retries (seconds) |

### Examples

**Disable connectivity checking** (trust network is always available):
```powershell
$env:G6_CONNECTIVITY_CHECK_ENABLED='false'
python scripts/run_orchestrator_loop.py
```

**Increase retry attempts** (for flaky connections):
```powershell
$env:G6_CONNECTIVITY_MAX_RETRIES='5'
$env:G6_CONNECTIVITY_RETRY_DELAY='3'
python scripts/run_orchestrator_loop.py
```

**Use custom check hosts**:
```powershell
$env:G6_CONNECTIVITY_CHECK_HOSTS='1.1.1.1,9.9.9.9'
python scripts/run_orchestrator_loop.py
```

## Retry Mechanisms

The platform has multiple layers of retry protection:

### 1. **Connectivity Layer** (New)
- Pre-cycle checks with retry
- Handles complete internet loss
- Prevents stuck cycles

### 2. **Provider Layer** (Existing)
- Built-in retry for API calls
- Handles transient errors: `TimeoutError`, `ConnectionError`
- Configurable via `G6_RETRY_*` variables

### 3. **Request Layer**
- HTTP timeout enforcement
- Thread-based timeout for stuck requests
- Synthetic fallback for zero/missing data

## Logging

### Normal Operation
```
DEBUG: Connectivity check passed (host=8.8.8.8)
```

### Connection Loss
```
WARNING: No internet connectivity detected, attempting recovery
WARNING: Connectivity check failed (attempt 1/3), retrying in 2.0s
INFO: Internet connectivity restored after 2 attempts
```

### Persistent Failure
```
ERROR: Failed to restore internet connectivity after 3 attempts
ERROR: Too many consecutive connectivity failures (3), exiting
```

## Best Practices

### Development
- Keep default settings (connectivity checks enabled)
- Monitor logs for connection issues
- Use `--cycles` flag for bounded test runs

### Production
- Enable connectivity checks (default)
- Set appropriate retry counts for your network reliability
- Monitor consecutive failure metrics
- Configure alerting on persistent failures

### Testing
- Disable checks for unit tests: `$env:G6_CONNECTIVITY_CHECK_ENABLED='false'`
- Use mock mode to avoid external network calls: `$env:G6_USE_MOCK_PROVIDER='1'`

## Troubleshooting

### Cycles still stuck after internet restored
**Cause**: Thread-based timeout doesn't kill stuck HTTP requests
**Solution**: Restart the orchestrator - connectivity checks prevent new stuck cycles

### False positive disconnection warnings
**Cause**: Check hosts may be blocked by firewall/network
**Solution**: Configure alternative check hosts via `G6_CONNECTIVITY_CHECK_HOSTS`

### Excessive retry attempts
**Cause**: Network is intermittently failing
**Solution**: Increase retry delay (`G6_CONNECTIVITY_RETRY_DELAY=5`) to give network time to stabilize

## Related Configuration

- `G6_RETRY_MAX_ATTEMPTS`: Provider-level retry attempts (default: 3)
- `G6_RETRY_MAX_SECONDS`: Provider-level max retry duration (default: 8s)
- `G6_RETRY_BACKOFF`: Provider-level backoff multiplier (default: 0.2)

## System Sleep Prevention

The orchestrator automatically prevents the system from sleeping during collection to ensure uninterrupted operation.

### Features
- **Automatic**: Enabled when orchestrator starts, disabled on exit
- **Cross-platform**: Windows, macOS, Linux support
- **Configurable**: Can be disabled if not needed
- **Safe**: Restores normal sleep behavior on crash or exit
- **No Admin Required**: Works with standard user privileges

### Platform Support

| Platform | Method | Status |
|----------|--------|--------|
| Windows | `SetThreadExecutionState` | ✅ Native API |
| macOS | `caffeinate` | ✅ System utility |
| Linux | `systemd-inhibit` | ✅ systemd integration |
| Other | None | ⚠️ No-op (sleep may occur) |

### Configuration

**Disable sleep prevention** (allow system to sleep normally):
```powershell
$env:G6_PREVENT_SLEEP='false'
python scripts/run_orchestrator_loop.py
```

**Custom wake reason** (Linux/macOS only):
```powershell
$env:G6_WAKE_REASON='Critical market data collection'
python scripts/run_orchestrator_loop.py
```

### Logging

```
INFO: System sleep prevention enabled
INFO: Sleep prevention enabled (Windows)
...
INFO: System sleep prevention disabled
```

### Administrator Rights

**No administrator/elevated privileges required!**

The sleep prevention uses user-level APIs:
- **Windows**: `SetThreadExecutionState` works for the current user session
- **macOS**: `caffeinate` runs as current user
- **Linux**: `systemd-inhibit` works for current user (not system-wide)

Simply run as your normal user:
```powershell
# No "Run as Administrator" needed
python scripts/run_orchestrator_loop.py
```

### Troubleshooting

**Sleep prevention not working?**
- Check logs for "Sleep prevention enabled" message
- Verify platform support (Windows/macOS/Linux)
- On Linux: ensure `systemd-inhibit` is installed
- On macOS: ensure running in terminal (not background service)
- **Not an admin rights issue** - API works for standard users

**Want to allow sleep?**
- Set `G6_PREVENT_SLEEP=false` in environment
- System will sleep normally per power settings

**Logs show "SetThreadExecutionState returned 0"?**
- Rare API failure (not permission-related)
- Collection continues, but system may sleep
- Report as bug with full logs

## See Also

- [Environment Variables](ENV_FLAGS_TABLES.md) - Full configuration reference
- [Error Handling](../architecture/ERROR_HANDLING.md) - Error taxonomy and recovery
- [Operator Manual](../guides/OPERATOR_MANUAL.md) - Production operations guide
