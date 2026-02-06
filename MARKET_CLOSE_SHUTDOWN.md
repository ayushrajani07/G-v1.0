# Market Close Shutdown Implementation

## Overview
Implemented automatic collector shutdown at the end of market trading hours to ensure the G6 platform stops data collection when markets close, preventing unnecessary API calls and resource usage.

## Features Implemented

### 1. Market Close Detection in Collection Loop
- **Implementation**: Orchestrator loop gating utilities
- **Location**: `src/orchestrator/gating.py` (`should_skip_cycle_market_hours`)
- **Trigger**: Enabled when market-hours gating is turned on (see Usage)

### 2. Market Hours Gating Behavior

When market-hours gating is enabled, cycles are skipped while the market is closed.
This prevents unnecessary provider calls and keeps the process idle until the next
open window.

### 3. Graceful Shutdown Process
1. **Detection**: Market close detected via `is_market_open()` function
2. **Logging**: Clear shutdown message logged  
3. **Loop Exit**: Clean break from main collection loop
4. **Cleanup**: Existing `finally` block in `main()` handles resource cleanup:
   - Health monitor shutdown
   - Provider connections closed
   - Metrics server stopped
   - Status polling thread terminated

## Usage

### Command Line Flag
```bash
python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60 --market-hours-only
```

### Configuration
Market-hours gating is controlled by `G6_LOOP_MARKET_HOURS=1` (the runner `--market-hours-only` flag sets it).

### Market Hours Configuration
Market hours are defined in `src/utils/market_hours.py`:
```python
DEFAULT_MARKET_HOURS = {
    "equity": {
        "regular": {"start": "09:15:00", "end": "15:30:00"},
    }
}
```

## Testing

### Test Files Created
1. **`test_market_close.py`**: Unit tests for market hours logic
2. **`test_unified_main_market_close.py`**: Integration tests for shutdown functionality

### Test Results
- ✅ Market close detection working correctly
- ✅ Graceful shutdown with proper logging
- ✅ No impact when `market_hours_only=False` 
- ✅ Clean resource cleanup on exit

## Benefits

### 1. Resource Optimization
- Stops unnecessary API calls after market close
- Reduces server resource usage during non-trading hours
- Prevents accumulation of stale data

### 2. Operational Efficiency  
- Automatic shutdown eliminates need for manual intervention
- Clear logging provides operational visibility
- Consistent behavior across different deployment scenarios

### 3. Cost Savings
- Reduces API usage costs from external providers
- Lower compute resource utilization
- Minimizes bandwidth usage

## Integration with Existing Code

### Backward Compatibility
- Existing behavior preserved when `market_hours_only=False`
- No changes to default configuration or API
- Graceful degradation if market hours detection fails

### Notes
- Legacy references to `collection_loop()` in `src/unified_main.py` are historical; the module is removed.
- Current gating is implemented via the orchestrator loop (`src/orchestrator/loop.py`) and helpers in `src/orchestrator/gating.py`.

## Example Log Output

```
INFO: Cycle completed in 2.45s
INFO: Market will close before next collection cycle. Stopping collector.
INFO: Shutting down G6 Platform
INFO: Stopping health monitor
INFO: Closing data providers  
INFO: Shutdown complete
```

## Configuration Examples

### Always Run (Default)
```json
{
  "market_hours_only": false
}
```

### Market Hours Only
```json
{
  "market_hours_only": true,
  "market_hours": {
    "equity": {
      "regular": {"start": "09:15:00", "end": "15:30:00"}
    }
  }
}
```

## Future Enhancements

### Potential Improvements
1. **Pre-market/Post-market Support**: Different shutdown logic for different trading sessions
2. **Holiday Detection**: Integration with trading calendar for market holidays
3. **Configurable Shutdown Delay**: Allow custom delay after market close
4. **Notification System**: Alert operators when automatic shutdown occurs

### Extension Points
- Market hours configuration via external API
- Custom shutdown callbacks for cleanup tasks
- Integration with external monitoring systems