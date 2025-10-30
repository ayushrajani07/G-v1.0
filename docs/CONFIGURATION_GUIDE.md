# G6 Platform - Configuration Guide

**Complete User Guide for Configuration Management**

---

## Table of Contents

1. [Overview](#1-overview)
2. [Configuration Files](#2-configuration-files)
3. [Environment Variables](#3-environment-variables)
4. [Config Loader](#4-config-loader)
5. [Feature Toggles](#5-feature-toggles)
6. [Complete Workflows](#6-complete-workflows)
7. [Configuration Reference](#7-configuration-reference)
8. [Troubleshooting](#8-troubleshooting)
9. [Best Practices](#9-best-practices)
10. [Summary](#10-summary)

---

## 1. Overview

### What is Configuration Management?

The G6 Platform uses a **layered configuration system** combining:

- **JSON files**: Structured config (`config/platform_config.json`)
- **Environment variables**: Runtime overrides (precedence over JSON)
- **Feature toggles**: Enable/disable features dynamically
- **Defaults**: Hardcoded fallbacks in code

### Configuration Precedence

```
1. Environment Variables (highest priority)
   ↓
2. JSON Configuration Files
   ↓
3. Code Defaults (lowest priority)
```

**Example**:
```bash
# Config file: {"metrics": {"port": 9108}}
# Env var: G6_METRICS_PORT=9109

# Result: 9109 (env var wins)
```

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Application Startup                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                ┌────────▼─────────┐
                │  ConfigLoader    │
                │  (load_config)   │
                └────────┬─────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
┌────────▼────────┐ ┌───▼────────┐ ┌───▼────────┐
│ platform_config │ │ env vars   │ │ defaults   │
│ .json           │ │ (G6_*)     │ │ (code)     │
└────────┬────────┘ └───┬────────┘ └───┬────────┘
         │              │              │
         └──────────────┼──────────────┘
                        │
               ┌────────▼─────────┐
               │  Merged Config   │
               │  (final values)  │
               └──────────────────┘
```

### File Structure

```
config/
├── platform_config.json     # Main configuration file
├── indices_config.json      # Index-specific settings
├── provider_config.json     # Provider settings (Kite, Mock)
└── storage_config.json      # Storage backends config

src/config/
├── __init__.py
├── config_loader.py         # ConfigLoader class
├── env_adapter.py           # Environment variable utilities
└── defaults.py              # Default values

docs/
├── ENV_FLAGS_TABLES.md      # Environment variables catalog
└── CONFIGURATION_GUIDE.md   # This guide
```

---

## 2. Configuration Files

### Main Config: platform_config.json

**Location**: `config/platform_config.json`

**Structure**:
```json
{
  "metrics": {
    "enabled": true,
    "port": 9108,
    "host": "0.0.0.0"
  },
  "collection": {
    "interval_seconds": 60,
    "retry_attempts": 3,
    "retry_delay_seconds": 5
  },
  "storage": {
    "csv_dir": "data/g6_data",
    "influx": {
      "enabled": false,
      "url": "http://localhost:8086",
      "token": "",
      "org": "g6platform",
      "bucket": "g6_data"
    }
  },
  "indices": {
    "NIFTY": {
      "enable": true,
      "expiries": ["this_week", "next_week"],
      "strikes_otm": 10,
      "strikes_itm": 10
    },
    "BANKNIFTY": {
      "enable": true,
      "expiries": ["this_week", "next_week"],
      "strikes_otm": 8,
      "strikes_itm": 8
    }
  },
  "provider": {
    "primary": "kite_live",
    "fallback": "mock",
    "timeout_seconds": 30,
    "rate_limit_per_second": 3
  },
  "analytics": {
    "enable_greeks": true,
    "enable_iv_calculation": true,
    "enable_pcr": true,
    "enable_vol_surface": false
  }
}
```

### Indices Config: indices_config.json

**Location**: `config/indices_config.json`

```json
{
  "NIFTY": {
    "enable": true,
    "symbol": "NIFTY 50",
    "lot_size": 50,
    "tick_size": 0.05,
    "expiries": ["this_week", "next_week"],
    "strikes": {
      "otm": 10,
      "itm": 10,
      "step": 50
    }
  },
  "BANKNIFTY": {
    "enable": true,
    "symbol": "NIFTY BANK",
    "lot_size": 25,
    "tick_size": 0.05,
    "expiries": ["this_week", "next_week", "monthly"],
    "strikes": {
      "otm": 15,
      "itm": 15,
      "step": 100
    }
  },
  "FINNIFTY": {
    "enable": false,
    "symbol": "NIFTY FIN SERVICE",
    "lot_size": 40,
    "tick_size": 0.05
  }
}
```

### Provider Config: provider_config.json

```json
{
  "kite_live": {
    "enabled": true,
    "api_key_env": "KITE_API_KEY",
    "access_token_env": "KITE_ACCESS_TOKEN",
    "timeout": 30,
    "retry_attempts": 3
  },
  "mock": {
    "enabled": true,
    "latency_ms": 50,
    "error_rate": 0.01
  },
  "synthetic": {
    "enabled": true,
    "seed": 42,
    "volatility": 0.15
  }
}
```

---

## 3. Environment Variables

### Core Platform

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `G6_ENV` | string | `development` | Environment (dev/staging/prod) |
| `G6_LOG_LEVEL` | string | `INFO` | Logging level |
| `G6_CONFIG_PATH` | string | `config/platform_config.json` | Config file path |
| `G6_DATA_DIR` | string | `data` | Base data directory |
| `G6_QUIET_LOGS` | bool | `0` | Suppress verbose logs |

### Metrics

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `G6_METRICS_ENABLED` | bool | `1` | Enable metrics server |
| `G6_METRICS_PORT` | int | `9108` | Prometheus port |
| `G6_METRICS_HOST` | string | `0.0.0.0` | Bind address |
| `G6_ENABLE_METRIC_GROUPS` | csv | ` ` | Allowlist metric groups |
| `G6_DISABLE_METRIC_GROUPS` | csv | ` ` | Blocklist metric groups |

### Collection

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `G6_COLLECTION_INTERVAL` | int | `60` | Collection cycle interval (seconds) |
| `G6_COLLECTION_RETRY_ATTEMPTS` | int | `3` | Retry attempts on failure |
| `G6_COLLECTION_TIMEOUT` | int | `30` | Collection timeout (seconds) |
| `G6_MARKET_HOURS_GATING` | bool | `1` | Enable market hours check |

### Storage

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `G6_CSV_DIR` | string | `data/g6_data` | CSV storage directory |
| `G6_CSV_BATCH_FLUSH` | int | `100` | Batch flush threshold |
| `G6_INFLUX_ENABLED` | bool | `0` | Enable InfluxDB |
| `G6_INFLUX_URL` | string | `http://localhost:8086` | InfluxDB URL |
| `G6_INFLUX_TOKEN` | string | ` ` | InfluxDB auth token |
| `G6_INFLUX_ORG` | string | `g6platform` | InfluxDB organization |
| `G6_INFLUX_BUCKET` | string | `g6_data` | InfluxDB bucket |

### Analytics

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `G6_ENABLE_GREEKS` | bool | `1` | Enable Greeks calculation |
| `G6_ENABLE_IV` | bool | `1` | Enable IV solver |
| `G6_ENABLE_PCR` | bool | `1` | Enable Put-Call Ratio |
| `G6_VOL_SURFACE` | bool | `0` | Enable vol surface (high cardinality) |
| `G6_RISK_AGG` | bool | `0` | Enable risk aggregation |

### Provider

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `G6_PROVIDER` | string | `kite_live` | Primary provider |
| `G6_PROVIDER_FALLBACK` | string | `mock` | Fallback provider |
| `KITE_API_KEY` | string | ` ` | Kite Connect API key |
| `KITE_ACCESS_TOKEN` | string | ` ` | Kite Connect access token |

### Feature Toggles

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `G6_ENABLE_PANELS` | bool | `1` | Enable panel generation |
| `G6_ENABLE_SSE` | bool | `0` | Enable SSE streaming |
| `G6_ENABLE_WEEKDAY_MASTER` | bool | `0` | Enable weekday master updates |
| `G6_ADAPTIVE_CONTROLLER` | bool | `0` | Enable adaptive controller |

---

## 4. Config Loader

### ConfigLoader Class

**Location**: `src/config/config_loader.py`

```python
from src.config.config_loader import load_config

# Load config from file
config = load_config("config/platform_config.json")

# Access nested values
metrics_port = config["metrics"]["port"]  # 9108
csv_dir = config["storage"]["csv_dir"]   # "data/g6_data"

# With fallback
influx_enabled = config.get("storage", {}).get("influx", {}).get("enabled", False)
```

### create_default_config()

**Auto-generates** config if file missing:

```python
from src.config.config_loader import create_default_config

# Generate default config
default = create_default_config()

# Write to file
import json
with open("config/platform_config.json", "w") as f:
    json.dump(default, f, indent=2)
```

### Environment Variable Adapter

**Location**: `src/config/env_adapter.py`

```python
from src.collectors.env_adapter import get_bool, get_int, get_str, get_float

# Type-safe env var access
metrics_enabled = get_bool("G6_METRICS_ENABLED", default=True)
metrics_port = get_int("G6_METRICS_PORT", default=9108)
csv_dir = get_str("G6_CSV_DIR", default="data/g6_data")
timeout = get_float("G6_TIMEOUT", default=30.0)
```

**Benefits**:
- Type conversion with validation
- Default values
- No crashes on missing vars
- Centralized env var access

---

## 5. Feature Toggles

### Toggle Pattern

Feature toggles allow **runtime enable/disable** without code changes.

```python
from src.collectors.env_adapter import get_bool

# Check toggle
if get_bool("G6_ENABLE_GREEKS", default=True):
    # Calculate Greeks
    greeks = calculate_greeks(option)
else:
    # Skip Greeks
    greeks = None
```

### Common Toggles

#### Disable High-Cardinality Metrics

```bash
# Disable vol surface metrics (saves Prometheus memory)
export G6_DISABLE_METRIC_GROUPS="analytics_vol_surface"
```

#### Enable Experimental Features

```bash
# Enable adaptive controller (experimental)
export G6_ADAPTIVE_CONTROLLER=1

# Enable SSE streaming
export G6_ENABLE_SSE=1
export G6_SSE_PORT=9315
```

#### Development Mode

```bash
# Use mock provider
export G6_PROVIDER=mock

# Disable rate limiting
export G6_RATE_LIMIT_ENABLED=0

# Enable verbose logging
export G6_LOG_LEVEL=DEBUG
export G6_QUIET_LOGS=0
```

---

## 6. Complete Workflows

### Workflow 1: Configure New Index

**Scenario**: Add MIDCPNIFTY index.

#### Step 1: Update Indices Config

Edit `config/indices_config.json`:

```json
{
  "MIDCPNIFTY": {
    "enable": true,
    "symbol": "NIFTY MIDCAP SELECT",
    "lot_size": 75,
    "tick_size": 0.05,
    "expiries": ["this_week", "next_week"],
    "strikes": {
      "otm": 8,
      "itm": 8,
      "step": 25
    }
  }
}
```

#### Step 2: Update Platform Config

Edit `config/platform_config.json`:

```json
{
  "indices": {
    "NIFTY": { ... },
    "BANKNIFTY": { ... },
    "MIDCPNIFTY": {  // NEW
      "enable": true,
      "expiries": ["this_week", "next_week"],
      "strikes_otm": 8,
      "strikes_itm": 8
    }
  }
}
```

#### Step 3: Restart Platform

```bash
python -m src.main
```

#### Step 4: Verify Collection

```bash
# Check status file
cat data/runtime_status.json | jq '.indices'

# Expected:
# ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"]

# Check CSV files
ls data/g6_data/options/MIDCPNIFTY/
```

---

### Workflow 2: Switch to Mock Provider

**Scenario**: Test without Kite API.

#### Step 1: Set Environment

```bash
export G6_PROVIDER=mock
export G6_MOCK_LATENCY_MS=50
export G6_MOCK_ERROR_RATE=0.01
```

#### Step 2: Start Platform

```bash
python -m src.main
```

**Output**:
```
INFO - Provider: mock (latency=50ms, error_rate=1%)
INFO - Starting collection cycle 1...
```

#### Step 3: Verify Data

```bash
# Check provider in status
cat data/runtime_status.json | jq '.provider'

# Expected:
# {
#   "name": "mock",
#   "latency_ms": 50
# }
```

---

### Workflow 3: Configure InfluxDB

**Scenario**: Enable time-series storage.

#### Step 1: Install InfluxDB

```bash
# Download from https://www.influxdata.com/downloads/
# Windows: Extract to C:\influxdb\

# Start InfluxDB
cd C:\influxdb
influxd.exe
```

#### Step 2: Create Org/Bucket/Token

```bash
# Open InfluxDB UI
http://localhost:8086

# Create:
# - Organization: g6platform
# - Bucket: g6_data
# - Token: (copy generated token)
```

#### Step 3: Configure Platform

```bash
export G6_INFLUX_ENABLED=1
export G6_INFLUX_URL=http://localhost:8086
export G6_INFLUX_ORG=g6platform
export G6_INFLUX_BUCKET=g6_data
export G6_INFLUX_TOKEN=your_token_here
```

Or update `config/platform_config.json`:

```json
{
  "storage": {
    "influx": {
      "enabled": true,
      "url": "http://localhost:8086",
      "token": "your_token_here",
      "org": "g6platform",
      "bucket": "g6_data"
    }
  }
}
```

#### Step 4: Restart & Verify

```bash
python -m src.main

# Check metrics
curl http://localhost:9108/metrics | grep influx

# Expected:
# g6_influx_points_written 1234
# g6_influx_write_errors 0
```

---

## 7. Configuration Reference

### Complete Environment Variables

See **[ENV_FLAGS_TABLES.md](ENV_FLAGS_TABLES.md)** for full catalog (200+ variables).

### Config File Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "G6 Platform Config",
  "type": "object",
  "properties": {
    "metrics": {
      "type": "object",
      "properties": {
        "enabled": {"type": "boolean"},
        "port": {"type": "integer", "minimum": 1024, "maximum": 65535},
        "host": {"type": "string"}
      }
    },
    "collection": {
      "type": "object",
      "properties": {
        "interval_seconds": {"type": "integer", "minimum": 1},
        "retry_attempts": {"type": "integer", "minimum": 0},
        "retry_delay_seconds": {"type": "number", "minimum": 0}
      }
    },
    "storage": {
      "type": "object",
      "properties": {
        "csv_dir": {"type": "string"},
        "influx": {
          "type": "object",
          "properties": {
            "enabled": {"type": "boolean"},
            "url": {"type": "string", "format": "uri"},
            "token": {"type": "string"},
            "org": {"type": "string"},
            "bucket": {"type": "string"}
          }
        }
      }
    },
    "indices": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "enable": {"type": "boolean"},
          "expiries": {"type": "array", "items": {"type": "string"}},
          "strikes_otm": {"type": "integer", "minimum": 0},
          "strikes_itm": {"type": "integer", "minimum": 0}
        }
      }
    }
  }
}
```

---

## 8. Troubleshooting

### Config File Not Found

**Symptom**: `FileNotFoundError: config/platform_config.json`

**Fix**:
```bash
# Generate default config
python -c "from src.config.config_loader import create_default_config; import json; json.dump(create_default_config(), open('config/platform_config.json', 'w'), indent=2)"

# Or create manually
mkdir -p config
echo '{"metrics": {"enabled": true, "port": 9108}}' > config/platform_config.json
```

### Environment Variable Not Applied

**Symptom**: Config value not overridden by env var.

**Debug**:
```python
import os
print(f"G6_METRICS_PORT={os.getenv('G6_METRICS_PORT')}")

from src.collectors.env_adapter import get_int
print(f"Parsed: {get_int('G6_METRICS_PORT', 9108)}")
```

**Fix**: Ensure env var exported before starting platform:
```bash
export G6_METRICS_PORT=9109
python -m src.main  # Must be in same shell session
```

### Invalid JSON

**Symptom**: `json.JSONDecodeError: Expecting ',' delimiter`

**Fix**:
```bash
# Validate JSON
python -m json.tool config/platform_config.json

# Fix syntax errors (missing commas, quotes)
```

---

## 9. Best Practices

### DO ✅

1. **Use environment variables for secrets**
   ```bash
   # Good
   export KITE_ACCESS_TOKEN=your_secret_token
   
   # Bad: hardcode in config file
   # {"provider": {"token": "your_secret_token"}}
   ```

2. **Version control config templates**
   ```bash
   # Commit templates
   git add config/platform_config.template.json
   
   # Ignore actual configs with secrets
   echo "config/platform_config.json" >> .gitignore
   ```

3. **Document all environment variables**
   ```python
   # In code
   METRICS_PORT = get_int("G6_METRICS_PORT", default=9108)
   # ^ Document in ENV_FLAGS_TABLES.md
   ```

4. **Validate config at startup**
   ```python
   from src.config.validate import validate_config
   
   config = load_config("config/platform_config.json")
   errors = validate_config(config)
   if errors:
       raise ValueError(f"Invalid config: {errors}")
   ```

### DON'T ❌

1. **Don't commit secrets**
   ```bash
   # Bad: commit tokens
   git add config/platform_config.json  # contains tokens
   
   # Good: use templates + env vars
   git add config/platform_config.template.json
   ```

2. **Don't hardcode paths**
   ```python
   # Bad
   csv_dir = "C:/Users/John/data/g6_data"
   
   # Good
   csv_dir = get_str("G6_CSV_DIR", default="data/g6_data")
   ```

3. **Don't skip validation**
   ```python
   # Bad: crash at runtime
   port = config["metrics"]["port"]  # KeyError if missing
   
   # Good: validate + fallback
   port = config.get("metrics", {}).get("port", 9108)
   ```

---

## 10. Summary

### Quick Start

```bash
# 1. Generate default config
python -c "from src.config.config_loader import create_default_config; import json; json.dump(create_default_config(), open('config/platform_config.json', 'w'), indent=2)"

# 2. Set environment overrides
export G6_PROVIDER=mock
export G6_METRICS_PORT=9109

# 3. Start platform
python -m src.main

# 4. Verify config
cat data/runtime_status.json | jq '.config_summary'
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Config Files** | JSON files for structured settings |
| **Environment Variables** | Runtime overrides (highest precedence) |
| **Feature Toggles** | Enable/disable features dynamically |
| **Config Loader** | Unified config loading with defaults |
| **Env Adapter** | Type-safe environment variable access |

### Related Guides

- **[Collector System Guide](COLLECTOR_SYSTEM_GUIDE.md)**: Provider configuration
- **[Storage Guide](STORAGE_GUIDE.md)**: Storage backend config
- **[Metrics Guide](METRICS_GUIDE.md)**: Metrics configuration
- **[Auth Guide](AUTH_GUIDE.md)**: Token management config

---

**End of Configuration Guide**
