# Storage & Persistence - Complete User Guide

## Overview

The **Storage System** manages persistent data storage for the G6 platform through multiple backends: CSV files (primary), InfluxDB (time-series), and optional column stores. This guide covers complete data persistence workflows, retention policies, and backfill procedures.

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    STORAGE PIPELINE                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────┐     │
│  │  COLLECTORS  │────▶│   STORAGE    │────▶│   SINKS     │     │
│  │              │     │              │     │             │     │
│  │ • Raw Data   │     │ • CSV Sink   │     │ • CSV Files │     │
│  │ • Analytics  │     │ • Influx     │     │ • InfluxDB  │     │
│  │ • Snapshots  │     │ • Buffers    │     │ • Archives  │     │
│  └──────────────┘     └──────────────┘     └─────────────┘     │
│         │                     │                     │            │
│         │                     │                     │            │
│         ▼                     ▼                     ▼            │
│  Per-cycle Data        Batching & Flush      Persistent Storage │
│  (Options, Spot,       Circuit Breaker       (Organized by      │
│   Analytics)           Retry Logic           Index/Expiry/Date) │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 1: CSV Storage (Primary Backend)

### What is CSV Sink?

The **CsvSink** is the primary storage backend that writes all market data to CSV files in a structured directory hierarchy. It provides:
- Deterministic file paths
- Atomic writes
- Daily file rotation
- Batch buffering
- Change tracking

### CsvSink Class

**File:** `src/storage/csv_sink.py` (2,100+ lines)

#### Initialization

```python
from src.storage.csv_sink import CsvSink

# Create CSV sink with default location
csv_sink = CsvSink(base_dir="data/g6_data")

# Custom location
csv_sink = CsvSink(base_dir="/mnt/storage/market_data")

# Attach metrics (optional)
from src.metrics import metrics
csv_sink.attach_metrics(metrics)
```

**Parameters:**
- `base_dir`: Root directory for CSV files (default: `data/g6_data`)
- Path resolution: Relative paths resolved from project root

**Directory Structure Created:**

```
data/g6_data/
├── options/                    # Options data
│   ├── NIFTY/
│   │   ├── 2025-11-28/        # Expiry date
│   │   │   ├── 0/             # ATM (offset 0)
│   │   │   │   └── 2025-10-25.csv
│   │   │   ├── 1/             # ATM+1
│   │   │   │   └── 2025-10-25.csv
│   │   │   └── -1/            # ATM-1
│   │   │       └── 2025-10-25.csv
│   │   └── 2025-12-26/        # Next expiry
│   │       └── ...
│   ├── BANKNIFTY/
│   │   └── ...
│   └── FINNIFTY/
│       └── ...
├── overview/                   # Index overview
│   ├── NIFTY/
│   │   └── 2025-10-25.csv
│   ├── BANKNIFTY/
│   │   └── 2025-10-25.csv
│   └── ...
├── analytics/                  # Analytics snapshots
│   ├── NIFTY/
│   │   └── 2025-10-25_analytics.csv
│   └── ...
└── snapshots/                  # Overview snapshots
    └── 2025-10-25_snapshot.json
```

### Writing Option Data

#### Single Option Write

```python
from datetime import datetime
from src.utils.timeutils import TIMEZONE_IST

# Write single option contract
csv_sink.write_option(
    index="NIFTY",
    expiry="2025-11-28",
    offset=0,                    # ATM offset
    timestamp=datetime.now(TIMEZONE_IST),
    data={
        "symbol": "NIFTY25NOV23500CE",
        "strike": 23500.0,
        "type": "CE",            # Call
        "last_price": 112.50,
        "volume": 1234567,
        "oi": 9876543,
        "bid": 112.0,
        "ask": 113.0,
        "iv": 15.3,
        "delta": 0.4523,
        "gamma": 0.000089,
        "theta": -5.23,
        "vega": 18.45
    }
)
```

**File Created:** `data/g6_data/options/NIFTY/2025-11-28/0/2025-10-25.csv`

**CSV Schema:**
```csv
timestamp,symbol,strike,type,last_price,volume,oi,bid,ask,iv,delta,gamma,theta,vega
09:30:00,NIFTY25NOV23500CE,23500.0,CE,112.50,1234567,9876543,112.0,113.0,15.3,0.4523,0.000089,-5.23,18.45
```

#### Batch Option Write

```python
# Write multiple options in batch (more efficient)
options_batch = []

for strike in [23400, 23450, 23500, 23550, 23600]:
    option_data = {
        "strike": strike,
        "symbol": f"NIFTY25NOV{strike}CE",
        "type": "CE",
        "last_price": calculate_price(strike),
        "volume": get_volume(strike),
        "oi": get_oi(strike),
        # ... other fields
    }
    options_batch.append(option_data)

# Write all at once
csv_sink.write_options_batch(
    index="NIFTY",
    expiry="2025-11-28",
    offset=0,
    timestamp=datetime.now(TIMEZONE_IST),
    options_data=options_batch
)
```

### Writing Overview Data

Overview files contain aggregated index data:

```python
# Write index overview
csv_sink.write_overview(
    index="NIFTY",
    timestamp=datetime.now(TIMEZONE_IST),
    data={
        "spot_price": 23450.25,
        "open": 23400.0,
        "high": 23500.0,
        "low": 23380.0,
        "close": 23450.25,
        "volume": 12345678,
        "pcr_oi": 1.23,
        "pcr_volume": 0.98,
        "atm_iv": 15.3,
        "vix": 12.5,
        "total_call_oi": 12345678,
        "total_put_oi": 15185185,
        "call_count": 45,
        "put_count": 45
    }
)
```

**File Created:** `data/g6_data/overview/NIFTY/2025-10-25.csv`

**CSV Schema:**
```csv
timestamp,spot_price,open,high,low,close,volume,pcr_oi,pcr_volume,atm_iv,vix,total_call_oi,total_put_oi,call_count,put_count
09:30:00,23450.25,23400.0,23500.0,23380.0,23450.25,12345678,1.23,0.98,15.3,12.5,12345678,15185185,45,45
```

### Batch Buffering

Enable batch buffering to reduce disk I/O:

```python
# Enable batch mode (flush after N writes)
import os
os.environ['G6_CSV_BATCH_FLUSH'] = '100'  # Flush every 100 rows

# Reinitialize sink to apply setting
csv_sink = CsvSink(base_dir="data/g6_data")

# Write multiple times
for i in range(150):
    csv_sink.write_option(...)  # Buffered in memory
    
# Automatic flush at 100 and 200 writes

# Manual flush (end of cycle)
csv_sink.flush_all_buffers()
```

**Buffering Configuration:**

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `G6_CSV_BATCH_FLUSH` | 0 | Rows before flush (0=disabled) |
| `G6_CSV_VERBOSE` | 1 | Log every write (0=silent) |
| `G6_CONCISE_LOGS` | 1 | Reduce repetitive logs |

### Change Tracking

CSV Sink tracks price changes automatically:

```python
# First write of the day
csv_sink.write_overview(
    index="NIFTY",
    timestamp=datetime(2025, 10, 25, 9, 15, 0, tzinfo=TIMEZONE_IST),
    data={"spot_price": 23400.0, "open": 23400.0, ...}
)
# Sets open price for the day

# Later write
csv_sink.write_overview(
    index="NIFTY",
    timestamp=datetime(2025, 10, 25, 15, 30, 0, tzinfo=TIMEZONE_IST),
    data={"spot_price": 23500.0, ...}
)
# Calculates day change: +100.0 points (+0.43%)

# Access tracked values
open_price = csv_sink._index_open_price.get("NIFTY")
last_price = csv_sink._index_last_price.get("NIFTY")
day_change = last_price - open_price if open_price else 0
```

### Previous Day Close

Load and track previous day close prices:

```python
def load_previous_close(csv_sink, index, current_date):
    """Load previous day close price"""
    from datetime import timedelta
    
    prev_date = current_date - timedelta(days=1)
    prev_file = f"data/g6_data/overview/{index}/{prev_date.strftime('%Y-%m-%d')}.csv"
    
    if os.path.exists(prev_file):
        import pandas as pd
        df = pd.read_csv(prev_file)
        if not df.empty:
            prev_close = df.iloc[-1]['spot_price']  # Last row = market close
            csv_sink._index_prev_close[index] = prev_close
            return prev_close
    
    return None

# Use for gap analysis
prev_close = load_previous_close(csv_sink, "NIFTY", date.today())
current_price = 23450.0

if prev_close:
    gap = ((current_price - prev_close) / prev_close) * 100
    print(f"Gap from previous close: {gap:.2f}%")
```

### File Path Resolution

```python
# Get file path for specific data
def get_option_file_path(csv_sink, index, expiry, offset, date):
    """Construct path to option CSV file"""
    date_str = date.strftime("%Y-%m-%d")
    path = os.path.join(
        csv_sink.base_dir,
        "options",
        index,
        expiry,
        str(offset),
        f"{date_str}.csv"
    )
    return path

# Example usage
file_path = get_option_file_path(
    csv_sink, 
    "NIFTY", 
    "2025-11-28", 
    0, 
    date(2025, 10, 25)
)
print(f"File: {file_path}")
# Output: data/g6_data/options/NIFTY/2025-11-28/0/2025-10-25.csv
```

---

## Part 2: InfluxDB Storage (Time-Series Backend)

### What is InfluxDB?

InfluxDB is a time-series database optimized for storing and querying timestamped data. The G6 platform optionally writes to InfluxDB for:
- Fast time-series queries
- Downsampling and aggregation
- Long-term retention with compression
- Grafana dashboard integration

### InfluxSink Class

**File:** `src/storage/influx_sink.py` (670+ lines)

#### Initialization

```python
from src.storage.influx_sink import InfluxSink

# Initialize InfluxDB sink
influx_sink = InfluxSink(
    url="http://localhost:8086",
    token="your_influxdb_token",
    org="g6",
    bucket="g6_data",
    batch_size=500,              # Batch size for writes
    flush_interval=10.0,         # Flush interval (seconds)
    max_retries=3,               # Retry failed writes
    breaker_fail_threshold=5,    # Circuit breaker threshold
    breaker_reset_timeout=30.0   # Circuit breaker reset time
)

# Connect to InfluxDB
influx_sink.connect()

# Attach metrics (optional)
from src.metrics import metrics
influx_sink.attach_metrics(metrics)
```

**Parameters:**
- `url`: InfluxDB server URL
- `token`: InfluxDB API token
- `org`: Organization name
- `bucket`: Bucket name
- `batch_size`: Number of points before flush
- `flush_interval`: Time before auto-flush (seconds)
- `max_retries`: Retry attempts for failed writes
- `breaker_fail_threshold`: Failures before circuit opens
- `breaker_reset_timeout`: Time before retry (seconds)

#### Environment Configuration

```bash
# InfluxDB connection
G6_INFLUX_URL=http://localhost:8086
G6_INFLUX_TOKEN=your_token_here
G6_INFLUX_ORG=g6
G6_INFLUX_BUCKET=g6_data

# Enable/disable InfluxDB
G6_ENABLE_INFLUX=1

# Performance tuning
G6_INFLUX_BATCH_SIZE=500
G6_INFLUX_FLUSH_INTERVAL=10.0
G6_INFLUX_MAX_RETRIES=3
```

### Writing Option Data to InfluxDB

```python
from datetime import datetime
from src.utils.timeutils import TIMEZONE_IST

# Write option data point
influx_sink.write_option(
    index="NIFTY",
    expiry="2025-11-28",
    strike=23500.0,
    option_type="CE",
    timestamp=datetime.now(TIMEZONE_IST),
    fields={
        "last_price": 112.50,
        "volume": 1234567,
        "oi": 9876543,
        "bid": 112.0,
        "ask": 113.0,
        "iv": 15.3,
        "delta": 0.4523,
        "gamma": 0.000089,
        "theta": -5.23,
        "vega": 18.45
    }
)
```

**InfluxDB Line Protocol:**
```
options,index=NIFTY,expiry=2025-11-28,strike=23500,type=CE last_price=112.5,volume=1234567i,oi=9876543i,bid=112.0,ask=113.0,iv=15.3,delta=0.4523,gamma=0.000089,theta=-5.23,vega=18.45 1729847400000000000
```

**Tags (Indexed):**
- `index`: Index name (NIFTY, BANKNIFTY, etc.)
- `expiry`: Expiry date (2025-11-28)
- `strike`: Strike price (23500)
- `type`: Option type (CE/PE)

**Fields (Not Indexed):**
- All numeric data (prices, volume, OI, Greeks)

### Writing Overview Data to InfluxDB

```python
# Write index overview
influx_sink.write_overview(
    index="NIFTY",
    timestamp=datetime.now(TIMEZONE_IST),
    fields={
        "spot_price": 23450.25,
        "open": 23400.0,
        "high": 23500.0,
        "low": 23380.0,
        "volume": 12345678,
        "pcr_oi": 1.23,
        "pcr_volume": 0.98,
        "atm_iv": 15.3,
        "vix": 12.5
    }
)
```

**InfluxDB Line Protocol:**
```
overview,index=NIFTY spot_price=23450.25,open=23400.0,high=23500.0,low=23380.0,volume=12345678i,pcr_oi=1.23,pcr_volume=0.98,atm_iv=15.3,vix=12.5 1729847400000000000
```

### Batching and Buffering

InfluxDB sink uses automatic batching:

```python
# Configure batch size
influx_sink = InfluxSink(
    url="http://localhost:8086",
    token="token",
    org="g6",
    bucket="g6_data",
    batch_size=1000,         # Buffer 1000 points
    flush_interval=5.0       # Or flush every 5 seconds
)

# Write 1500 points
for i in range(1500):
    influx_sink.write_option(...)  # Auto-flushes at 1000

# Manual flush (end of cycle)
influx_sink.flush()
```

**Flush Triggers:**
1. Batch size reached (`batch_size` points buffered)
2. Time interval elapsed (`flush_interval` seconds)
3. Manual flush (`flush()` called)
4. Shutdown/cleanup

### Circuit Breaker

Protects against overwhelming failed InfluxDB:

```python
# Circuit breaker states:
# - CLOSED: Normal operation
# - OPEN: Too many failures, reject writes
# - HALF_OPEN: Testing if backend recovered

# Check circuit state
if influx_sink.circuit_breaker.is_open():
    print("Circuit OPEN - InfluxDB unavailable")
    # Fall back to CSV only
else:
    print("Circuit CLOSED - InfluxDB operational")

# Circuit opens after 5 failures (configurable)
# Resets after 30 seconds (configurable)

# Monitor circuit breaker
from src.metrics import metrics
metrics.influx_circuit_breaker_state.set(
    1 if influx_sink.circuit_breaker.is_open() else 0
)
```

### Connection Pooling

InfluxDB sink uses connection pooling:

```python
# Pool configuration (automatic)
influx_sink = InfluxSink(
    url="http://localhost:8086",
    token="token",
    org="g6",
    bucket="g6_data",
    pool_min_size=1,     # Minimum connections
    pool_max_size=2      # Maximum connections
)

# Pool manages connections automatically
# Reuses connections across writes
# Handles reconnection on failure
```

### Retry Logic

Failed writes automatically retry with exponential backoff:

```python
# Retry configuration
influx_sink = InfluxSink(
    url="http://localhost:8086",
    token="token",
    org="g6",
    bucket="g6_data",
    max_retries=3,           # Try 3 times
    backoff_base=0.25        # 0.25s, 0.5s, 1.0s delays
)

# Automatic retry sequence:
# 1. First attempt fails
# 2. Wait 0.25s, retry (attempt 2)
# 3. Wait 0.5s, retry (attempt 3)
# 4. Wait 1.0s, retry (attempt 4)
# 5. If all fail, circuit breaker opens
```

### Querying InfluxDB Data

```python
from influxdb_client import InfluxDBClient

# Create query client
client = InfluxDBClient(
    url="http://localhost:8086",
    token="your_token",
    org="g6"
)

query_api = client.query_api()

# Flux query for NIFTY spot prices
flux_query = '''
from(bucket: "g6_data")
  |> range(start: -1d)
  |> filter(fn: (r) => r._measurement == "overview")
  |> filter(fn: (r) => r.index == "NIFTY")
  |> filter(fn: (r) => r._field == "spot_price")
  |> yield(name: "spot_prices")
'''

# Execute query
result = query_api.query(flux_query)

# Process results
for table in result:
    for record in table.records:
        print(f"{record.get_time()}: {record.get_value()}")

client.close()
```

**Common Queries:**

```python
# 1. Get ATM option prices for last hour
flux_query = '''
from(bucket: "g6_data")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "options")
  |> filter(fn: (r) => r.index == "NIFTY")
  |> filter(fn: (r) => r.strike == "23500")
  |> filter(fn: (r) => r.type == "CE")
  |> filter(fn: (r) => r._field == "last_price")
'''

# 2. Calculate average PCR for today
flux_query = '''
from(bucket: "g6_data")
  |> range(start: today())
  |> filter(fn: (r) => r._measurement == "overview")
  |> filter(fn: (r) => r.index == "NIFTY")
  |> filter(fn: (r) => r._field == "pcr_oi")
  |> mean()
'''

# 3. Get IV for all strikes at specific time
flux_query = '''
from(bucket: "g6_data")
  |> range(start: 2025-10-25T09:30:00Z, stop: 2025-10-25T09:31:00Z)
  |> filter(fn: (r) => r._measurement == "options")
  |> filter(fn: (r) => r.index == "NIFTY")
  |> filter(fn: (r) => r._field == "iv")
  |> pivot(rowKey: ["_time"], columnKey: ["strike"], valueColumn: "_value")
'''
```

---

## Part 3: Data Access Layer

### Reading CSV Files

#### Direct Pandas Access

```python
import pandas as pd
import os

def read_option_data(index, expiry, offset, date):
    """Read option data for specific date"""
    file_path = f"data/g6_data/options/{index}/{expiry}/{offset}/{date}.csv"
    
    if not os.path.exists(file_path):
        return None
    
    df = pd.read_csv(file_path)
    return df

# Usage
df = read_option_data("NIFTY", "2025-11-28", 0, "2025-10-25")

if df is not None:
    print(f"Loaded {len(df)} rows")
    print(df.head())
```

#### Read Multiple Days

```python
from datetime import datetime, timedelta

def read_option_range(index, expiry, offset, start_date, end_date):
    """Read option data for date range"""
    all_data = []
    
    current = start_date
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        df = read_option_data(index, expiry, offset, date_str)
        
        if df is not None:
            df['date'] = date_str
            all_data.append(df)
        
        current += timedelta(days=1)
    
    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return None

# Usage
start = datetime(2025, 10, 1)
end = datetime(2025, 10, 25)
df = read_option_range("NIFTY", "2025-11-28", 0, start, end)

print(f"Loaded {len(df)} rows across {(end-start).days + 1} days")
```

#### Read All Offsets

```python
def read_all_offsets(index, expiry, date, offset_range=(-5, 5)):
    """Read all strike offsets for a date"""
    all_offsets = {}
    
    for offset in range(offset_range[0], offset_range[1] + 1):
        df = read_option_data(index, expiry, offset, date)
        if df is not None:
            all_offsets[offset] = df
    
    return all_offsets

# Usage
offset_data = read_all_offsets("NIFTY", "2025-11-28", "2025-10-25")

for offset, df in offset_data.items():
    print(f"Offset {offset}: {len(df)} rows")
```

### Reading Overview Data

```python
def read_overview(index, date):
    """Read overview data for specific date"""
    file_path = f"data/g6_data/overview/{index}/{date}.csv"
    
    if not os.path.exists(file_path):
        return None
    
    df = pd.read_csv(file_path)
    return df

# Usage
overview = read_overview("NIFTY", "2025-10-25")

if overview is not None:
    # Get specific metrics
    print(f"Day Open: {overview.iloc[0]['spot_price']}")
    print(f"Day Close: {overview.iloc[-1]['spot_price']}")
    print(f"Day High: {overview['high'].max()}")
    print(f"Day Low: {overview['low'].min()}")
    print(f"Average PCR: {overview['pcr_oi'].mean():.2f}")
```

### Data Access Utilities

```python
class DataAccessor:
    """Utility class for accessing stored data"""
    
    def __init__(self, base_dir="data/g6_data"):
        self.base_dir = base_dir
    
    def list_available_dates(self, index, data_type="overview"):
        """List all available dates for an index"""
        dir_path = os.path.join(self.base_dir, data_type, index)
        
        if not os.path.exists(dir_path):
            return []
        
        dates = []
        for file in os.listdir(dir_path):
            if file.endswith('.csv'):
                date_str = file.replace('.csv', '')
                dates.append(date_str)
        
        return sorted(dates)
    
    def list_expiries(self, index):
        """List all expiries for an index"""
        dir_path = os.path.join(self.base_dir, "options", index)
        
        if not os.path.exists(dir_path):
            return []
        
        expiries = []
        for expiry_dir in os.listdir(dir_path):
            expiry_path = os.path.join(dir_path, expiry_dir)
            if os.path.isdir(expiry_path):
                expiries.append(expiry_dir)
        
        return sorted(expiries)
    
    def get_latest_overview(self, index):
        """Get most recent overview data"""
        dates = self.list_available_dates(index, "overview")
        
        if not dates:
            return None
        
        latest_date = dates[-1]
        return read_overview(index, latest_date)
    
    def get_storage_stats(self):
        """Get storage statistics"""
        stats = {
            "indices": [],
            "total_files": 0,
            "total_size_mb": 0
        }
        
        # Count files and sizes
        for root, dirs, files in os.walk(self.base_dir):
            for file in files:
                if file.endswith('.csv'):
                    file_path = os.path.join(root, file)
                    stats["total_files"] += 1
                    stats["total_size_mb"] += os.path.getsize(file_path) / (1024 * 1024)
        
        # List indices
        overview_dir = os.path.join(self.base_dir, "overview")
        if os.path.exists(overview_dir):
            stats["indices"] = sorted(os.listdir(overview_dir))
        
        return stats

# Usage
accessor = DataAccessor()

# List available data
dates = accessor.list_available_dates("NIFTY")
print(f"NIFTY data available for {len(dates)} dates")

expiries = accessor.list_expiries("NIFTY")
print(f"NIFTY expiries: {expiries}")

# Get latest data
latest = accessor.get_latest_overview("NIFTY")
if latest is not None:
    print(f"Latest spot: {latest.iloc[-1]['spot_price']}")

# Storage statistics
stats = accessor.get_storage_stats()
print(f"Total files: {stats['total_files']}")
print(f"Total size: {stats['total_size_mb']:.2f} MB")
print(f"Indices: {stats['indices']}")
```

---

## Part 4: Retention & Archival

### Retention Policies

Define data retention policies:

```python
# Configuration
RETENTION_POLICY = {
    "intraday_options": 90,      # 90 days
    "overview": 365,             # 1 year
    "analytics": 180,            # 6 months
    "snapshots": 30              # 30 days
}

def apply_retention_policy(base_dir, policy):
    """Remove data older than retention period"""
    from datetime import datetime, timedelta
    
    today = datetime.now().date()
    
    for data_type, days in policy.items():
        cutoff_date = today - timedelta(days=days)
        
        # Find and remove old files
        type_dir = os.path.join(base_dir, data_type)
        if not os.path.exists(type_dir):
            continue
        
        for index_dir in os.listdir(type_dir):
            index_path = os.path.join(type_dir, index_dir)
            if not os.path.isdir(index_path):
                continue
            
            for file in os.listdir(index_path):
                if not file.endswith('.csv'):
                    continue
                
                # Extract date from filename
                try:
                    file_date = datetime.strptime(
                        file.replace('.csv', ''), 
                        '%Y-%m-%d'
                    ).date()
                    
                    if file_date < cutoff_date:
                        file_path = os.path.join(index_path, file)
                        os.remove(file_path)
                        print(f"Removed old file: {file_path}")
                
                except ValueError:
                    continue

# Run retention cleanup
apply_retention_policy("data/g6_data", RETENTION_POLICY)
```

### Archival to Compressed Storage

```python
import shutil
from datetime import datetime, timedelta

def archive_old_data(base_dir, archive_dir, days_old=90):
    """Archive data older than specified days"""
    today = datetime.now().date()
    cutoff = today - timedelta(days=days_old)
    
    os.makedirs(archive_dir, exist_ok=True)
    
    # Create monthly archives
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if not file.endswith('.csv'):
                continue
            
            try:
                file_date = datetime.strptime(
                    file.replace('.csv', ''),
                    '%Y-%m-%d'
                ).date()
                
                if file_date < cutoff:
                    # Determine archive file (monthly)
                    year_month = file_date.strftime('%Y-%m')
                    archive_file = os.path.join(
                        archive_dir,
                        f"{year_month}.tar.gz"
                    )
                    
                    # Add to archive (create if doesn't exist)
                    source_file = os.path.join(root, file)
                    # ... (use tarfile to add to archive)
                    
                    # Remove original
                    os.remove(source_file)
                    print(f"Archived: {file} → {archive_file}")
            
            except ValueError:
                continue

# Run archival
archive_old_data(
    base_dir="data/g6_data",
    archive_dir="data/archives",
    days_old=90
)
```

---

## Part 5: Backfill & Recovery

### Backfill Missing Data

```python
def backfill_missing_dates(index, start_date, end_date, provider, csv_sink):
    """Backfill missing data for date range"""
    from datetime import timedelta
    
    current = start_date
    backfilled_count = 0
    
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        
        # Check if data exists
        overview_file = f"data/g6_data/overview/{index}/{date_str}.csv"
        
        if not os.path.exists(overview_file):
            print(f"Backfilling {index} for {date_str}...")
            
            try:
                # Fetch historical data from provider
                spot_data = provider.get_historical_data(index, current)
                
                # Write to CSV
                for timestamp, data in spot_data.items():
                    csv_sink.write_overview(
                        index=index,
                        timestamp=timestamp,
                        data=data
                    )
                
                backfilled_count += 1
                print(f"✓ Backfilled {date_str}")
            
            except Exception as e:
                print(f"✗ Failed to backfill {date_str}: {e}")
        
        current += timedelta(days=1)
    
    print(f"Backfill complete: {backfilled_count} dates")

# Usage
from datetime import date
from src.broker.kite_provider import KiteProvider

provider = KiteProvider()
csv_sink = CsvSink()

backfill_missing_dates(
    index="NIFTY",
    start_date=date(2025, 10, 1),
    end_date=date(2025, 10, 25),
    provider=provider,
    csv_sink=csv_sink
)
```

### Verify Data Integrity

```python
def verify_data_integrity(base_dir, index, date):
    """Verify data integrity for specific date"""
    issues = []
    
    # Check overview file
    overview_file = f"{base_dir}/overview/{index}/{date}.csv"
    if not os.path.exists(overview_file):
        issues.append(f"Missing overview file for {date}")
    else:
        df = pd.read_csv(overview_file)
        if df.empty:
            issues.append(f"Empty overview file for {date}")
        
        # Check for missing timestamps
        if len(df) < 375:  # Expect ~375 minutes in trading day
            issues.append(f"Incomplete overview data: {len(df)} rows")
    
    # Check options files
    expiries = os.listdir(f"{base_dir}/options/{index}")
    for expiry in expiries:
        for offset in range(-5, 6):
            option_file = f"{base_dir}/options/{index}/{expiry}/{offset}/{date}.csv"
            
            if os.path.exists(option_file):
                df = pd.read_csv(option_file)
                if df.empty:
                    issues.append(f"Empty option file: {expiry}/offset{offset}")
    
    return issues

# Usage
issues = verify_data_integrity("data/g6_data", "NIFTY", "2025-10-25")

if issues:
    print("Data integrity issues found:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("✓ Data integrity verified")
```

---

## Part 6: Configuration Reference

### CSV Storage Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `G6_CSV_BASE_DIR` | `data/g6_data` | Base directory for CSV files |
| `G6_CSV_BATCH_FLUSH` | 0 | Batch size before flush (0=disabled) |
| `G6_CSV_VERBOSE` | 1 | Log every write operation |
| `G6_CONCISE_LOGS` | 1 | Reduce repetitive log output |
| `G6_OVERVIEW_INTERVAL_SECONDS` | 180 | Overview aggregation interval |

### InfluxDB Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `G6_INFLUX_URL` | `http://localhost:8086` | InfluxDB server URL |
| `G6_INFLUX_TOKEN` | - | InfluxDB API token |
| `G6_INFLUX_ORG` | `g6` | Organization name |
| `G6_INFLUX_BUCKET` | `g6_data` | Bucket name |
| `G6_ENABLE_INFLUX` | 0 | Enable InfluxDB storage |
| `G6_INFLUX_BATCH_SIZE` | 500 | Points per batch |
| `G6_INFLUX_FLUSH_INTERVAL` | 10.0 | Flush interval (seconds) |
| `G6_INFLUX_MAX_RETRIES` | 3 | Retry attempts |
| `G6_INFLUX_BREAKER_THRESHOLD` | 5 | Circuit breaker threshold |

---

## Summary

The **Storage System** provides:

✅ **CSV Storage** - Primary file-based persistence  
✅ **InfluxDB** - Optional time-series database  
✅ **Batch Buffering** - Optimized disk I/O  
✅ **Circuit Breaker** - Resilient InfluxDB writes  
✅ **Data Access** - Utilities for reading stored data  
✅ **Retention** - Automated data lifecycle  

**Quick Start:**

```python
from src.storage.csv_sink import CsvSink
from src.storage.influx_sink import InfluxSink

# CSV storage (always enabled)
csv_sink = CsvSink(base_dir="data/g6_data")

# InfluxDB storage (optional)
influx_sink = InfluxSink(
    url="http://localhost:8086",
    token="your_token",
    org="g6",
    bucket="g6_data"
)
influx_sink.connect()

# Write data to both
csv_sink.write_overview(index="NIFTY", timestamp=now, data=overview_data)
influx_sink.write_overview(index="NIFTY", timestamp=now, fields=overview_data)
```

**Next Guide:** `docs/METRICS_GUIDE.md` - Monitoring and observability

---

*For data schema details, see `docs/UNIFIED_MODEL.md`*
