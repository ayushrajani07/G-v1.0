# Data Collection System - Complete User Guide

## Overview

The **Data Collection System** is the heart of the G6 platform, responsible for gathering real-time market data from brokers (primarily Zerodha Kite), processing it through multiple stages, and orchestrating the entire collection cycle. This guide covers the complete collection pipeline from providers to storage.

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   DATA COLLECTION PIPELINE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────┐     │
│  │   PROVIDERS  │────▶│  COLLECTORS  │────▶│   STORAGE   │     │
│  │              │     │              │     │             │     │
│  │ • Kite Live  │     │ • Pipeline   │     │ • CSV Sink  │     │
│  │ • Mock Data  │     │ • Modules    │     │ • InfluxDB  │     │
│  │ • Synthetic  │     │ • Analytics  │     │ • Status    │     │
│  └──────────────┘     └──────────────┘     └─────────────┘     │
│         │                     │                     │            │
│         │                     │                     │            │
│         ▼                     ▼                     ▼            │
│  ┌─────────────────────────────────────────────────────┐        │
│  │           ORCHESTRATOR (Cycle Management)            │        │
│  │  • Market hours gating                               │        │
│  │  • Interval timing (60s default)                    │        │
│  │  • Graceful shutdown                                 │        │
│  │  • Error handling & resilience                      │        │
│  └─────────────────────────────────────────────────────┘        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Providers System

### What are Providers?

Providers are the data source abstraction layer that fetch market data from external sources. They provide a unified interface regardless of whether you're using live broker APIs, mock data, or synthetic test data.

### Available Providers

#### 1. **Kite Live Provider** (Production)

**File:** `src/broker/kite_provider.py`  
**Purpose:** Live market data from Zerodha Kite Connect API  
**Use When:** Production trading, live market hours

**Features:**
- Real-time quotes for indices and options
- Instrument resolution (trading symbols ↔ tokens)
- Expiry date discovery
- Rate limiting (respects Kite API limits: 3 req/sec)
- Token caching (6-hour TTL)
- Automatic retry with exponential backoff

**Configuration:**

```python
# Environment variables
G6_KITE_API_KEY=your_api_key_here
G6_KITE_API_SECRET=your_api_secret_here
G6_KITE_ACCESS_TOKEN=your_access_token_here

# Rate limiting
G6_KITE_RATE_LIMIT=3           # Requests per second
G6_KITE_RATE_WINDOW=1.0        # Time window (seconds)

# Caching
G6_KITE_CACHE_TTL=21600        # 6 hours in seconds
```

**Example Usage:**

```python
from src.broker.kite_provider import KiteProvider

# Initialize provider
provider = KiteProvider(
    api_key=os.getenv("G6_KITE_API_KEY"),
    api_secret=os.getenv("G6_KITE_API_SECRET"),
    access_token=os.getenv("G6_KITE_ACCESS_TOKEN")
)

# Get spot quote
spot_data = provider.get_spot_quote("NIFTY")
print(f"NIFTY: {spot_data['last_price']}")

# Get option chain
expiry = provider.get_next_expiry("NIFTY")
options = provider.get_option_chain("NIFTY", expiry, atm_strikes=10)
print(f"Fetched {len(options)} option contracts")
```

**Error Handling:**

```python
from src.utils.resilience import with_retry, CircuitBreaker

# Built-in retry logic
@with_retry(max_attempts=3, backoff_factor=2.0)
def fetch_with_retry():
    return provider.get_spot_quote("NIFTY")

# Circuit breaker for repeated failures
circuit = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60.0
)

if not circuit.is_open():
    try:
        data = provider.get_option_chain("NIFTY", expiry)
        circuit.record_success()
    except Exception as e:
        circuit.record_failure()
        logger.error(f"Provider error: {e}")
```

#### 2. **Mock Provider** (Development)

**File:** `src/providers/mock_provider.py`  
**Purpose:** Deterministic test data without external dependencies  
**Use When:** Development, testing, CI/CD pipelines

**Features:**
- Deterministic synthetic data
- No external API calls
- Configurable volatility and patterns
- Instant responses (no rate limits)
- Market hours simulation

**Configuration:**

```python
# Enable mock provider
G6_USE_MOCK_PROVIDER=1

# Mock data parameters
G6_MOCK_SPOT_BASE=23500.0              # NIFTY base price
G6_MOCK_VOLATILITY=0.15                # 15% annual volatility
G6_MOCK_SIMULATE_DELAYS=0              # Add realistic delays (0=off)
```

**Example Usage:**

```python
from src.providers.mock_provider import MockProvider

# Initialize with base prices
provider = MockProvider(
    spot_bases={
        "NIFTY": 23500.0,
        "BANKNIFTY": 51000.0,
        "FINNIFTY": 21500.0,
        "SENSEX": 77000.0
    }
)

# Get mock spot data (deterministic)
spot = provider.get_spot_quote("NIFTY")
print(f"Mock NIFTY: {spot['last_price']}")  # Always returns predictable value

# Get mock option chain
options = provider.get_option_chain("NIFTY", expiry="2025-11-28", atm_strikes=5)
# Returns synthetic options with realistic Greeks and IV
```

**Mock Data Characteristics:**

```python
# Spot prices: base ± random walk within volatility bounds
# Options: Black-Scholes pricing with:
#   - IV: 15-25% for ATM, higher for OTM
#   - Greeks: Calculated accurately
#   - Bid-Ask spread: 0.5% of mid price
#   - OI: Randomized realistic values
```

#### 3. **Synthetic Provider** (Testing)

**File:** `src/synthetic/synthetic_provider.py`  
**Purpose:** Programmable test scenarios (edge cases, stress tests)  
**Use When:** Unit tests, integration tests, benchmarking

**Features:**
- Fully programmable responses
- Inject specific error conditions
- Control timing and latency
- Simulate partial outages
- Reproducible test scenarios

**Example Usage:**

```python
from src.synthetic.synthetic_provider import SyntheticProvider

# Create provider with test scenario
provider = SyntheticProvider()

# Program specific responses
provider.set_spot_response("NIFTY", {
    "last_price": 23450.25,
    "open": 23400.0,
    "high": 23500.0,
    "low": 23380.0,
    "volume": 1234567
})

# Inject errors for testing
provider.set_error_for_index("BANKNIFTY", "Rate limit exceeded")

# Simulate latency
provider.set_latency_ms(500)  # 500ms delay for all calls

# Test error handling
try:
    data = provider.get_spot_quote("BANKNIFTY")
except Exception as e:
    print(f"Expected error: {e}")
```

### Provider Interface (Abstract)

**File:** `src/collectors/providers_interface.py`

All providers implement the same interface:

```python
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

class ProviderInterface(ABC):
    @abstractmethod
    def get_spot_quote(self, index: str) -> Dict:
        """Get current spot price and OHLCV data"""
        pass
    
    @abstractmethod
    def get_option_chain(
        self, 
        index: str, 
        expiry: str, 
        atm_strikes: int = 10
    ) -> List[Dict]:
        """Get option chain data for given expiry"""
        pass
    
    @abstractmethod
    def get_next_expiry(self, index: str) -> str:
        """Get next weekly/monthly expiry date"""
        pass
    
    @abstractmethod
    def resolve_instrument(self, symbol: str) -> Optional[int]:
        """Convert trading symbol to instrument token"""
        pass
    
    @abstractmethod
    def health_check(self) -> bool:
        """Check if provider is operational"""
        pass
```

### Provider Selection Logic

**File:** `src/orchestrator/bootstrap.py`

```python
def select_provider() -> ProviderInterface:
    """Auto-select provider based on environment"""
    
    # Priority 1: Mock (explicit override)
    if os.getenv("G6_USE_MOCK_PROVIDER", "0") == "1":
        logger.info("Using MockProvider (G6_USE_MOCK_PROVIDER=1)")
        return MockProvider()
    
    # Priority 2: Synthetic (testing mode)
    if os.getenv("G6_USE_SYNTHETIC", "0") == "1":
        logger.info("Using SyntheticProvider (testing)")
        return SyntheticProvider()
    
    # Priority 3: Live Kite (production)
    if all([
        os.getenv("G6_KITE_API_KEY"),
        os.getenv("G6_KITE_ACCESS_TOKEN")
    ]):
        logger.info("Using KiteProvider (live data)")
        return KiteProvider()
    
    # Fallback: Mock with warning
    logger.warning("No provider credentials found, falling back to MockProvider")
    return MockProvider()
```

**Quick Selection:**

```powershell
# Use mock provider (safe, no credentials needed)
$env:G6_USE_MOCK_PROVIDER='1'
python scripts/run_orchestrator_loop.py

# Use live Kite (requires credentials)
$env:G6_KITE_API_KEY='your_key'
$env:G6_KITE_ACCESS_TOKEN='your_token'
python scripts/run_orchestrator_loop.py

# Use synthetic (testing only)
$env:G6_USE_SYNTHETIC='1'
pytest tests/
```

---

## Part 2: Collectors System

### What are Collectors?

Collectors orchestrate the data collection process for each index during each cycle. They coordinate between providers, analytics, and storage systems.

### Architecture

```
Collection Cycle (per index, per interval):

1. FETCH (Provider)
   ├─ Get spot quote
   ├─ Resolve expiry dates
   └─ Fetch option chain
   
2. PROCESS (Analytics)
   ├─ Calculate IV (Implied Volatility)
   ├─ Compute Greeks (Delta, Gamma, Vega, Theta)
   ├─ Aggregate PCR (Put-Call Ratio)
   └─ Build breadth indicators
   
3. STORE (Persistence)
   ├─ Write CSV files
   ├─ Push to InfluxDB (optional)
   └─ Update status manifest
   
4. EMIT (Observability)
   ├─ Update Prometheus metrics
   ├─ Write panels JSON
   └─ Log structured events
```

### Main Collector Module

**File:** `src/collectors/unified_collectors.py`

#### Core Functions

##### 1. **collect_for_index()**

Main entry point for collecting data for a single index.

```python
def collect_for_index(
    index: str,
    provider: ProviderInterface,
    csv_sink: CsvSink,
    influx_sink: Optional[InfluxSink],
    config: Dict,
    cycle_num: int
) -> CollectionResult:
    """
    Collect complete data for one index in one cycle.
    
    Args:
        index: Index name (NIFTY, BANKNIFTY, etc.)
        provider: Data source implementation
        csv_sink: CSV storage handler
        influx_sink: InfluxDB storage (optional)
        config: Configuration dict
        cycle_num: Current cycle number
        
    Returns:
        CollectionResult with success status, metrics, and errors
    """
```

**Usage Example:**

```python
from src.collectors.unified_collectors import collect_for_index
from src.broker.kite_provider import KiteProvider
from src.storage.csv_sink import CsvSink

# Setup
provider = KiteProvider()
csv_sink = CsvSink(base_dir="data/g6_data")
config = {
    "strikes_offset": 10,  # ATM ± 10 strikes
    "enable_analytics": True,
    "enable_influx": False
}

# Collect for NIFTY
result = collect_for_index(
    index="NIFTY",
    provider=provider,
    csv_sink=csv_sink,
    influx_sink=None,
    config=config,
    cycle_num=1
)

if result.success:
    print(f"✓ Collected {result.options_count} options")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    print(f"  Spot: {result.spot_price}")
else:
    print(f"✗ Collection failed: {result.error_message}")
```

##### 2. **build_overview_snapshot()**

Creates aggregated overview with PCR, breadth, and completeness metrics.

```python
def build_overview_snapshot(
    index: str,
    spot_data: Dict,
    options_data: List[Dict],
    analytics: Dict,
    timestamp: datetime
) -> Dict:
    """
    Build overview snapshot with aggregated metrics.
    
    Returns:
        {
            "timestamp": "2025-10-25T09:30:00+05:30",
            "index": "NIFTY",
            "spot_price": 23450.25,
            "pcr_oi": 1.23,
            "pcr_volume": 0.98,
            "atm_iv": 15.3,
            "call_count": 45,
            "put_count": 45,
            "total_call_oi": 1234567,
            "total_put_oi": 1520000,
            "breadth": {
                "calls_itm": 20,
                "calls_otm": 25,
                "puts_itm": 25,
                "puts_otm": 20
            }
        }
    """
```

**Example:**

```python
# After fetching spot and options
overview = build_overview_snapshot(
    index="NIFTY",
    spot_data=spot,
    options_data=options,
    analytics=greeks_results,
    timestamp=datetime.now(TIMEZONE_IST)
)

# Use overview for monitoring
if overview["pcr_oi"] > 1.5:
    logger.warning(f"High PCR detected: {overview['pcr_oi']}")
```

### Collection Pipeline

**File:** `src/collectors/pipeline.py`

The pipeline provides a structured, staged approach to data collection:

```python
from src.collectors.pipeline import CollectionPipeline

# Create pipeline
pipeline = CollectionPipeline(
    provider=provider,
    csv_sink=csv_sink,
    influx_sink=influx_sink,
    config=config
)

# Add pre-processing hooks
@pipeline.before_fetch
def log_start(index: str, cycle: int):
    logger.info(f"Starting collection: {index} cycle {cycle}")

# Add post-processing hooks
@pipeline.after_store
def emit_metrics(index: str, result: CollectionResult):
    metrics.collection_duration.labels(index=index).observe(result.duration_seconds)
    metrics.options_collected.labels(index=index).set(result.options_count)

# Run pipeline for index
result = pipeline.run(index="NIFTY", cycle_num=1)
```

### Collector Modules

**Directory:** `src/collectors/modules/`

Specialized modules for specific collection aspects:

#### 1. **Strike Depth Calculator** (`strike_depth.py`)

Determines how many strikes to fetch based on ATM and market conditions.

```python
from src.collectors.modules.strike_depth import calculate_strike_depth

# Dynamic strike depth
depth = calculate_strike_depth(
    index="NIFTY",
    spot_price=23450.0,
    base_depth=10,           # Base ATM ± 10
    volatility=0.15,         # 15% IV
    adaptive=True            # Adjust based on volatility
)

print(f"Fetch ATM ± {depth} strikes")  # May return 15 if high volatility
```

#### 2. **Aggregation Module** (`aggregation.py`)

Computes PCR, breadth, and aggregated metrics.

```python
from src.collectors.modules.aggregation import compute_pcr, compute_breadth

# Put-Call Ratio
pcr_oi = compute_pcr(options, metric="oi")          # By open interest
pcr_volume = compute_pcr(options, metric="volume")  # By volume

# Market breadth
breadth = compute_breadth(options, spot_price=23450.0)
print(f"Bullish breadth: {breadth['calls_itm']}/{breadth['calls_otm']}")
print(f"Bearish breadth: {breadth['puts_itm']}/{breadth['puts_otm']}")
```

#### 3. **Coverage Module** (`coverage.py`)

Tracks data completeness and quality metrics.

```python
from src.collectors.modules.coverage import assess_coverage

# Check data quality
coverage = assess_coverage(
    index="NIFTY",
    expected_strikes=20,
    actual_strikes=18,
    expected_expiries=4,
    actual_expiries=4
)

if not coverage["is_complete"]:
    logger.warning(f"Incomplete data: {coverage['missing_strikes']} strikes missing")
```

### Collector Settings

**File:** `src/collector/settings.py`

Centralized configuration for collectors:

```python
from dataclasses import dataclass
from src.collector.settings import CollectorSettings

@dataclass
class CollectorSettings:
    # Collection parameters
    strikes_offset: int = 10              # ATM ± strikes
    max_concurrent_indices: int = 4       # Parallel collection
    collection_timeout: float = 30.0      # Per-index timeout (seconds)
    
    # Resilience
    enable_circuit_breaker: bool = True
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: float = 60.0
    
    # Analytics
    enable_greeks: bool = True
    enable_iv_calculation: bool = True
    iv_solver_max_iterations: int = 100
    
    # Storage
    enable_csv: bool = True
    enable_influx: bool = False
    csv_base_dir: str = "data/g6_data"
    
    # Logging
    log_level: str = "INFO"
    log_detailed_errors: bool = True

# Load from environment
settings = CollectorSettings.from_env()

# Override specific settings
settings.strikes_offset = 15
settings.enable_influx = True
```

**Environment Variables:**

```bash
# Collection settings
G6_STRIKES_OFFSET=10
G6_MAX_CONCURRENT_INDICES=4
G6_COLLECTION_TIMEOUT=30.0

# Analytics toggles
G6_ENABLE_GREEKS=1
G6_ENABLE_IV_CALCULATION=1

# Storage configuration
G6_CSV_BASE_DIR=data/g6_data
G6_ENABLE_INFLUX=0
G6_INFLUX_URL=http://localhost:8086

# Logging
G6_LOG_LEVEL=INFO
G6_LOG_DETAILED_ERRORS=1
```

---

## Part 3: Orchestrator System

### What is the Orchestrator?

The orchestrator is the "brain" of the collection system, managing lifecycle, timing, and coordination of all collection cycles.

### Main Orchestrator

**File:** `src/orchestrator/orchestrator.py`

#### Core Functions

##### 1. **bootstrap_runtime()**

Initialize all systems before starting collection loop.

```python
def bootstrap_runtime(config: Dict) -> RuntimeContext:
    """
    Bootstrap the complete runtime environment.
    
    Initializes:
    - Configuration loading
    - Provider selection
    - Storage systems (CSV, InfluxDB)
    - Metrics server
    - Health checks
    - Logging
    
    Returns:
        RuntimeContext: Initialized runtime state
    """
```

**Usage:**

```python
from src.orchestrator.orchestrator import bootstrap_runtime

# Bootstrap with config
runtime = bootstrap_runtime(config={
    "indices": ["NIFTY", "BANKNIFTY", "FINNIFTY"],
    "interval": 60,
    "max_cycles": None,  # Infinite
    "market_hours_only": True
})

# Access initialized components
provider = runtime.provider
csv_sink = runtime.csv_sink
metrics_server = runtime.metrics_server
```

##### 2. **run_loop()**

Main collection loop with market hours gating and graceful shutdown.

```python
def run_loop(
    runtime: RuntimeContext,
    interval: int = 60,
    max_cycles: Optional[int] = None,
    market_hours_only: bool = True
) -> None:
    """
    Run the collection loop.
    
    Args:
        runtime: Initialized runtime context
        interval: Seconds between cycles (default 60)
        max_cycles: Maximum cycles to run (None = infinite)
        market_hours_only: Only run during market hours
        
    Behavior:
        - Waits until market open if market_hours_only=True
        - Runs collection cycle every interval seconds
        - Stops at market close if market_hours_only=True
        - Handles Ctrl+C gracefully
        - Logs all errors but continues running
    """
```

**Example:**

```python
# Run collection loop
run_loop(
    runtime=runtime,
    interval=60,              # Every 60 seconds
    max_cycles=None,          # Run until market close
    market_hours_only=True    # Only during 9:15 AM - 3:30 PM IST
)
```

##### 3. **run_cycle()**

Execute one complete collection cycle across all indices.

```python
def run_cycle(
    runtime: RuntimeContext,
    cycle_num: int
) -> CycleResult:
    """
    Execute one collection cycle for all configured indices.
    
    Args:
        runtime: Runtime context with providers and storage
        cycle_num: Current cycle number (for logging)
        
    Returns:
        CycleResult with:
        - success: bool
        - indices_collected: List[str]
        - indices_failed: List[str]
        - duration_seconds: float
        - errors: List[str]
    """
```

**Cycle Flow:**

```python
# Cycle 1 execution
cycle_result = run_cycle(runtime, cycle_num=1)

if cycle_result.success:
    print(f"✓ Cycle {cycle_num} completed in {cycle_result.duration_seconds:.2f}s")
    print(f"  Successful: {cycle_result.indices_collected}")
else:
    print(f"✗ Cycle {cycle_num} had errors:")
    for error in cycle_result.errors:
        print(f"  - {error}")
```

### Runtime Context

**File:** `src/orchestrator/context.py`

```python
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class RuntimeContext:
    """Complete runtime state for orchestration"""
    
    # Core components
    provider: ProviderInterface
    csv_sink: CsvSink
    influx_sink: Optional[InfluxSink]
    
    # Configuration
    indices: List[str]
    config: Dict
    
    # State tracking
    cycle_count: int = 0
    start_time: datetime = None
    last_cycle_time: datetime = None
    
    # Feature flags
    enable_analytics: bool = True
    enable_panels: bool = True
    enable_metrics: bool = True
    
    # Performance tracking
    cycle_durations: List[float] = None
    error_counts: Dict[str, int] = None
    
    def increment_cycle(self) -> int:
        """Increment and return cycle number"""
        self.cycle_count += 1
        self.last_cycle_time = datetime.now(TIMEZONE_IST)
        return self.cycle_count
    
    def record_cycle_duration(self, duration: float) -> None:
        """Track cycle performance"""
        if self.cycle_durations is None:
            self.cycle_durations = []
        self.cycle_durations.append(duration)
    
    def record_error(self, index: str) -> None:
        """Track errors by index"""
        if self.error_counts is None:
            self.error_counts = {}
        self.error_counts[index] = self.error_counts.get(index, 0) + 1
```

### Market Hours Gating

**File:** `src/utils/timeutils.py`

```python
from src.utils.timeutils import is_market_open, wait_until_market_open, time_until_market_close

# Check if currently in market hours
if is_market_open():
    print("Market is open, starting collection")
else:
    print("Market is closed")

# Wait until market opens
print("Waiting for market to open...")
wait_until_market_open()  # Blocks until 9:15 AM IST
print("Market opened, starting collection")

# Check time remaining
minutes_left = time_until_market_close() / 60
print(f"Market closes in {minutes_left:.1f} minutes")
```

### Graceful Shutdown

```python
import signal
import sys

def setup_signal_handlers(runtime: RuntimeContext):
    """Setup graceful shutdown on Ctrl+C"""
    
    def shutdown_handler(signum, frame):
        logger.info("Shutdown signal received, cleaning up...")
        
        # Stop metrics server
        if runtime.metrics_server:
            runtime.metrics_server.stop()
        
        # Close storage connections
        if runtime.influx_sink:
            runtime.influx_sink.close()
        
        # Flush pending writes
        runtime.csv_sink.flush()
        
        # Log final stats
        logger.info(f"Total cycles: {runtime.cycle_count}")
        logger.info(f"Average duration: {sum(runtime.cycle_durations)/len(runtime.cycle_durations):.2f}s")
        
        sys.exit(0)
    
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
```

---

## Part 4: Complete Workflow Examples

### Example 1: Simple Collection Script

```python
#!/usr/bin/env python3
"""
Simple data collection script
Collects data for NIFTY every 60 seconds during market hours
"""

import os
from datetime import datetime
from src.orchestrator.orchestrator import bootstrap_runtime, run_loop
from src.utils.timeutils import TIMEZONE_IST

# Configuration
config = {
    "indices": ["NIFTY"],
    "strikes_offset": 10,
    "enable_analytics": True,
    "enable_influx": False,
    "csv_base_dir": "data/g6_data"
}

# Enable mock provider for testing
os.environ["G6_USE_MOCK_PROVIDER"] = "1"

# Bootstrap
print(f"[{datetime.now(TIMEZONE_IST)}] Initializing collection system...")
runtime = bootstrap_runtime(config)

# Run collection loop
print(f"[{datetime.now(TIMEZONE_IST)}] Starting collection loop (60s interval)")
run_loop(
    runtime=runtime,
    interval=60,
    max_cycles=None,
    market_hours_only=True
)
```

**Run it:**

```powershell
python scripts/simple_collect.py
```

### Example 2: Multi-Index Collection

```python
#!/usr/bin/env python3
"""
Multi-index collection with analytics and InfluxDB
"""

from src.orchestrator.orchestrator import bootstrap_runtime, run_loop

# Configuration for all major indices
config = {
    "indices": ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"],
    "strikes_offset": 15,
    "enable_analytics": True,
    "enable_greeks": True,
    "enable_iv_calculation": True,
    "enable_influx": True,
    "csv_base_dir": "data/g6_data",
    "influx_url": "http://localhost:8086",
    "influx_bucket": "g6_data",
    "influx_org": "g6"
}

# Bootstrap with full configuration
runtime = bootstrap_runtime(config)

# Add monitoring hooks
@runtime.on_cycle_complete
def log_cycle_stats(result):
    print(f"Cycle {result.cycle_num} complete:")
    print(f"  Successful: {', '.join(result.indices_collected)}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    if result.indices_failed:
        print(f"  Failed: {', '.join(result.indices_failed)}")

# Run with 30-second interval
run_loop(runtime, interval=30, market_hours_only=True)
```

### Example 3: Testing with Synthetic Data

```python
#!/usr/bin/env python3
"""
Test collection pipeline with synthetic data
"""

import os
from src.collectors.unified_collectors import collect_for_index
from src.synthetic.synthetic_provider import SyntheticProvider
from src.storage.csv_sink import CsvSink

# Use synthetic provider
os.environ["G6_USE_SYNTHETIC"] = "1"
provider = SyntheticProvider()

# Program test scenario
provider.set_spot_response("NIFTY", {
    "last_price": 23450.0,
    "open": 23400.0,
    "high": 23500.0,
    "low": 23380.0
})

# Setup storage
csv_sink = CsvSink(base_dir="data/test_output")

# Collect test data
result = collect_for_index(
    index="NIFTY",
    provider=provider,
    csv_sink=csv_sink,
    influx_sink=None,
    config={"strikes_offset": 5, "enable_analytics": False},
    cycle_num=1
)

# Verify results
assert result.success, f"Collection failed: {result.error_message}"
assert result.options_count > 0, "No options collected"
print(f"✓ Test passed: Collected {result.options_count} options")
```

---

## Part 5: Configuration Reference

### Collection Configuration Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `indices` | List[str] | ["NIFTY", "BANKNIFTY"] | Indices to collect |
| `strikes_offset` | int | 10 | ATM ± strikes to fetch |
| `interval` | int | 60 | Seconds between cycles |
| `max_cycles` | int\|None | None | Maximum cycles (None = infinite) |
| `market_hours_only` | bool | True | Only run during market hours |
| `enable_analytics` | bool | True | Calculate IV & Greeks |
| `enable_greeks` | bool | True | Compute option Greeks |
| `enable_iv_calculation` | bool | True | Calculate implied volatility |
| `enable_csv` | bool | True | Write CSV files |
| `enable_influx` | bool | False | Write to InfluxDB |
| `csv_base_dir` | str | "data/g6_data" | CSV output directory |
| `collection_timeout` | float | 30.0 | Per-index timeout (seconds) |
| `max_concurrent_indices` | int | 4 | Parallel collection limit |

### Provider Configuration

#### Kite Provider

| Environment Variable | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `G6_KITE_API_KEY` | Yes | - | Your Kite API key |
| `G6_KITE_API_SECRET` | Yes | - | Your Kite API secret |
| `G6_KITE_ACCESS_TOKEN` | Yes | - | Valid access token |
| `G6_KITE_RATE_LIMIT` | No | 3 | Requests per second |
| `G6_KITE_RATE_WINDOW` | No | 1.0 | Rate limit window (seconds) |
| `G6_KITE_CACHE_TTL` | No | 21600 | Token cache TTL (6 hours) |
| `G6_KITE_TIMEOUT` | No | 10.0 | Request timeout (seconds) |

#### Mock Provider

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `G6_USE_MOCK_PROVIDER` | 0 | Enable mock provider |
| `G6_MOCK_SPOT_BASE` | 23500.0 | NIFTY base price |
| `G6_MOCK_VOLATILITY` | 0.15 | Annual volatility (15%) |
| `G6_MOCK_SIMULATE_DELAYS` | 0 | Simulate realistic delays |

### Collector Settings

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `G6_STRIKES_OFFSET` | 10 | ATM ± strikes |
| `G6_MAX_CONCURRENT_INDICES` | 4 | Parallel collection |
| `G6_COLLECTION_TIMEOUT` | 30.0 | Per-index timeout |
| `G6_ENABLE_CIRCUIT_BREAKER` | 1 | Enable circuit breaker |
| `G6_CIRCUIT_FAILURE_THRESHOLD` | 5 | Failures before opening |
| `G6_CIRCUIT_RECOVERY_TIMEOUT` | 60.0 | Recovery period (seconds) |

---

## Part 6: Monitoring & Troubleshooting

### Collection Metrics

**Exposed via Prometheus at `http://localhost:9108/metrics`:**

```promql
# Collection success rate
rate(g6_collection_success_total[5m])

# Collection duration
histogram_quantile(0.95, g6_collection_duration_seconds_bucket)

# Options collected per cycle
g6_options_collected_total{index="NIFTY"}

# Collection errors
rate(g6_collection_errors_total{index="NIFTY"}[5m])

# Provider health
g6_provider_health_status{provider="kite"}

# Circuit breaker status
g6_circuit_breaker_state{index="NIFTY"}
```

### Common Issues

#### Issue 1: "Rate limit exceeded"

**Cause:** Too many API calls to Kite Connect  
**Solution:**

```python
# Reduce strikes offset
G6_STRIKES_OFFSET=5  # Instead of 10

# Increase interval
interval = 120  # Instead of 60 seconds

# Enable rate limiter
G6_KITE_RATE_LIMIT=2  # Conservative: 2 req/sec
```

#### Issue 2: "Collection timeout"

**Cause:** Slow provider response or network issues  
**Solution:**

```python
# Increase timeout
G6_COLLECTION_TIMEOUT=60.0  # Instead of 30.0

# Check provider health
if not provider.health_check():
    logger.error("Provider unhealthy")

# Enable circuit breaker
G6_ENABLE_CIRCUIT_BREAKER=1
```

#### Issue 3: "No data collected"

**Cause:** Outside market hours or invalid credentials  
**Solution:**

```python
from src.utils.timeutils import is_market_open

# Check market hours
if not is_market_open():
    print("Market is closed")

# Verify credentials
if not os.getenv("G6_KITE_ACCESS_TOKEN"):
    print("Missing access token")

# Test with mock provider
os.environ["G6_USE_MOCK_PROVIDER"] = "1"
```

#### Issue 4: "Memory usage growing"

**Cause:** Cache not being cleared, data accumulation  
**Solution:**

```python
# Clear caches periodically
@runtime.on_cycle_complete
def clear_caches(result):
    if result.cycle_num % 10 == 0:  # Every 10 cycles
        provider.clear_cache()
        csv_sink.flush_buffers()

# Limit cycle history
runtime.cycle_durations = runtime.cycle_durations[-100:]  # Keep last 100
```

### Health Checks

```python
from src.health.health_checker import HealthChecker

# Create health checker
health = HealthChecker(runtime)

# Check provider
if not health.check_provider():
    logger.error("Provider unhealthy")

# Check storage
if not health.check_storage():
    logger.error("Storage unhealthy")

# Check overall system
if health.is_healthy():
    print("✓ All systems operational")
else:
    print("✗ System degraded")
    for component, status in health.get_status().items():
        print(f"  {component}: {status}")
```

### Debug Mode

```python
# Enable debug logging
G6_LOG_LEVEL=DEBUG
G6_LOG_DETAILED_ERRORS=1

# Enable collector debug mode
G6_COLLECTOR_DEBUG=1

# Enable provider debug
G6_PROVIDER_DEBUG=1

# Log all API calls
G6_LOG_API_CALLS=1
```

---

## Part 7: Best Practices

### ✅ DO

1. **Use mock provider for development:**
   ```python
   G6_USE_MOCK_PROVIDER=1  # Safe, no credentials needed
   ```

2. **Respect rate limits:**
   ```python
   G6_KITE_RATE_LIMIT=3  # Don't exceed Kite limits
   interval = 60          # Reasonable interval
   ```

3. **Enable circuit breakers:**
   ```python
   G6_ENABLE_CIRCUIT_BREAKER=1
   G6_CIRCUIT_FAILURE_THRESHOLD=5
   ```

4. **Monitor metrics:**
   ```python
   # Check Prometheus metrics regularly
   # Alert on high error rates
   ```

5. **Handle errors gracefully:**
   ```python
   @with_retry(max_attempts=3)
   def collect_with_retry():
       return collect_for_index(...)
   ```

6. **Use market hours gating:**
   ```python
   run_loop(market_hours_only=True)  # Save API quota
   ```

### ❌ DON'T

1. **Don't ignore rate limits** - You'll get banned
2. **Don't run without error handling** - System will crash
3. **Don't collect outside market hours** - Wastes API quota
4. **Don't use production credentials in tests** - Use mock provider
5. **Don't skip health checks** - Monitor system state
6. **Don't collect more data than needed** - Control strikes_offset

---

## Part 8: VS Code Tasks

Access via **Terminal → Run Task...**

### Collection Tasks

- **"Smoke: Start Simulator"** - Run with synthetic data
- **"G6: Init Menu"** - Interactive configuration wizard
- **"Observability: Start baseline"** - Start with monitoring stack

---

## Summary

The **Data Collection System** provides:

✅ **Flexible Providers** - Live, Mock, Synthetic data sources  
✅ **Robust Collection** - Error handling, retries, circuit breakers  
✅ **Orchestration** - Market hours gating, graceful shutdown  
✅ **Configurability** - Environment variables and config files  
✅ **Monitoring** - Prometheus metrics, health checks  
✅ **Testing** - Synthetic data, mock providers  

**Quick Start Commands:**

```powershell
# Development (mock data)
$env:G6_USE_MOCK_PROVIDER='1'
python scripts/run_orchestrator_loop.py --interval 60

# Production (live Kite data)
$env:G6_KITE_API_KEY='your_key'
$env:G6_KITE_ACCESS_TOKEN='your_token'
python scripts/run_orchestrator_loop.py --interval 60 --market-hours-only

# Testing
$env:G6_USE_SYNTHETIC='1'
pytest tests/test_collectors.py
```

**Next Steps:**
1. Review `docs/ANALYTICS_GUIDE.md` for Greeks and IV calculations
2. Review `docs/STORAGE_GUIDE.md` for CSV and InfluxDB persistence
3. Review `docs/METRICS_GUIDE.md` for Prometheus monitoring

---

*For system architecture details, see `docs/ARCHITECTURE.md`*
