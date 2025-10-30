# G6 Platform - Complete User Guide

**Comprehensive Guide for Options Trading Platform**

---

## 📚 Table of Contents

- [1. Introduction](#1-introduction)
- [2. Getting Started](#2-getting-started)
- [3. Module Guides](#3-module-guides)
- [4. Reference Documentation](#4-reference-documentation)
- [5. Quick Reference](#5-quick-reference)
- [6. Use Cases & Workflows](#6-use-cases--workflows)
- [7. Troubleshooting](#7-troubleshooting)
- [8. Contributing](#8-contributing)

---

## 1. Introduction

### What is G6?

**G6** is a high-throughput, modular options market data collection & analytics platform for Indian indices (NIFTY, BANKNIFTY, FINNIFTY, SENSEX). It performs minute-level collection cycles, computes derived analytics (IV, Greeks, PCR), writes durable snapshots (CSV + optional InfluxDB), and exposes rich observability (Prometheus metrics, Grafana dashboards, real-time panels).

### Key Features

✅ **Real-time Data Collection**: Minute-level cycles with market hours gating  
✅ **Options Analytics**: IV solver, Greeks (Delta/Gamma/Vega/Theta/Rho), PCR  
✅ **Multiple Providers**: Kite Live, Mock (testing), Synthetic (simulation)  
✅ **Dual Storage**: CSV (primary) + InfluxDB (optional time-series)  
✅ **Observability**: 145+ Prometheus metrics, Grafana dashboards, integrity monitoring  
✅ **Real-time Dashboards**: Rich terminal UI + plain text + SSE streaming  
✅ **Weekday Master**: Historical data aggregation for backtesting  
✅ **Comprehensive Testing**: 250+ tests, 85%+ coverage, two-phase (parallel+serial)  

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     G6 Platform                             │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Orchestrator │───▶│  Collectors  │───▶│   Storage    │  │
│  │  (Lifecycle) │    │  (Pipeline)  │    │  (CSV/Influx)│  │
│  └──────┬───────┘    └──────┬───────┘    └──────────────┘  │
│         │                    │                               │
│         │            ┌───────▼────────┐                      │
│         │            │   Analytics    │                      │
│         │            │ (IV, Greeks)   │                      │
│         │            └────────────────┘                      │
│         │                                                    │
│  ┌──────▼───────┐   ┌──────────────┐   ┌──────────────┐    │
│  │  Providers   │   │   Metrics    │   │    Panels    │    │
│  │ (Kite/Mock)  │   │ (Prometheus) │   │  (Real-time) │    │
│  └──────────────┘   └──────────────┘   └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### System Requirements

- **Python**: 3.10+ (tested on 3.10, 3.11, 3.12)
- **OS**: Windows 10/11, Linux (Ubuntu 20.04+), macOS
- **Memory**: 2GB minimum, 4GB recommended
- **Disk**: 10GB for data storage
- **Network**: Internet connection for Kite API (optional for mock mode)

---

## 2. Getting Started

### Installation

#### Step 1: Clone Repository

```bash
git clone https://github.com/yourusername/g6_reorganized.git
cd g6_reorganized
```

#### Step 2: Create Virtual Environment

```bash
# Create venv
python -m venv .venv

# Activate (Windows)
.\.venv\Scripts\Activate.ps1

# Activate (Linux/Mac)
source .venv/bin/activate
```

#### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

#### Step 4: Configure Platform

```bash
# Copy config template
cp config/platform_config.template.json config/platform_config.json

# Edit config (optional - defaults work for mock mode)
notepad config/platform_config.json
```

### Quick Start (Mock Mode)

Test the platform without live API:

```bash
# Set mock provider
export G6_PROVIDER=mock

# Run collection cycle
python -m src.main

# View real-time summary
python -m scripts.summary.app --refresh 1
```

### Quick Start (Live Mode)

Requires Kite Connect API credentials:

```bash
# Step 1: Get API credentials from https://kite.zerodha.com/apps

# Step 2: Set credentials
export KITE_API_KEY=your_api_key
export KITE_API_SECRET=your_api_secret

# Step 3: Generate token (interactive)
python -m src.tools.token_manager

# Step 4: Start platform
python -m src.main

# Step 5: View summary
python -m scripts.summary.app --refresh 1
```

### VS Code Setup (Recommended)

The platform includes pre-configured VS Code tasks:

```bash
# Open in VS Code
code .

# Available tasks (Ctrl+Shift+P → "Tasks: Run Task"):
# - G6: Init Menu (interactive launcher)
# - Smoke: Start Simulator (generate test data)
# - Smoke: Summary Demo (view summary)
# - pytest: two-phase (run tests)
# - Observability: Start baseline (Prometheus + Grafana)
```

---

## 3. Module Guides

### Core Module Guides

Comprehensive guides for each major platform component:

#### 📊 [Data Collection System](COLLECTOR_SYSTEM_GUIDE.md) (1,300+ lines)
Complete guide for market data collection pipeline.

**Topics Covered:**
- Provider selection (Kite Live, Mock, Synthetic)
- Collection cycle workflow
- Pipeline architecture
- Orchestrator lifecycle management
- Market hours gating
- Error handling & resilience
- Monitoring & troubleshooting

**When to Read:** Setting up data collection, configuring providers, debugging collection issues

---

#### 📈 [Analytics & Greeks](ANALYTICS_GUIDE.md) (1,800+ lines)
Complete guide for options analytics calculations.

**Topics Covered:**
- OptionGreeks class (Delta, Gamma, Vega, Theta, Rho)
- Implied Volatility solver (Newton-Raphson method)
- Black-Scholes pricing model
- Put-Call Ratio (PCR) calculation
- Market breadth analysis
- Volatility surface construction
- IV smile/skew analysis

**When to Read:** Understanding analytics, debugging IV solver, customizing Greeks calculations

---

#### 💾 [Storage & Persistence](STORAGE_GUIDE.md) (1,500+ lines)
Complete guide for data storage systems.

**Topics Covered:**
- CSV Sink (primary file-based storage)
- InfluxDB Sink (optional time-series database)
- Directory structure and file formats
- Batch buffering and circuit breakers
- Data access layer (reading stored data)
- Retention policies and archival
- Backfill and recovery procedures

**When to Read:** Configuring storage, setting up InfluxDB, data access patterns, retention management

---

#### 📊 [Metrics & Monitoring](METRICS_GUIDE.md) (2,000+ lines)
Complete guide for Prometheus metrics and observability.

**Topics Covered:**
- 145+ metrics catalog
- MetricsRegistry singleton
- Metric groups and gating
- Cardinality management (preventing label explosion)
- Grafana dashboard integration
- Recording rules and alert rules
- Performance monitoring
- Custom metrics creation

**When to Read:** Setting up monitoring, creating Grafana dashboards, adding custom metrics, debugging high cardinality

---

#### 📱 [Panels & Dashboards](PANELS_GUIDE.md) (1,400+ lines)
Complete guide for real-time panel system.

**Topics Covered:**
- Panel factory and builders
- Summary application (Rich/Plain rendering modes)
- Panel integrity monitoring (hash-based verification)
- Status manifests and structured JSON
- SSE streaming for browser dashboards
- Panel providers and rendering

**When to Read:** Building custom panels, setting up terminal UI, SSE streaming, integrity monitoring

---

#### ⚙️ [Configuration Management](CONFIGURATION_GUIDE.md) (1,200+ lines)
Complete guide for configuration and environment variables.

**Topics Covered:**
- JSON configuration files
- Environment variable precedence
- Feature toggles and flags
- ConfigLoader class
- Configuration governance
- Validation and schemas

**When to Read:** Configuring platform, environment setup, feature toggles, configuration troubleshooting

---

#### 🔐 [Authentication & Tokens](AUTH_GUIDE.md) (1,100+ lines)
Complete guide for Kite Connect authentication.

**Topics Covered:**
- OAuth 2.0 authentication flow
- Token manager CLI tool
- Token storage (environment, file, in-memory)
- Auto-refresh and expiry handling
- Headless authentication for CI/CD
- Secret management

**When to Read:** Setting up Kite authentication, token management, CI/CD automation, handling token expiry

---

#### 🧪 [Testing Infrastructure](TESTING_GUIDE.md) (1,500+ lines)
Complete guide for testing with pytest.

**Topics Covered:**
- 250+ test suite overview
- Two-phase testing (parallel + serial)
- pytest configuration and fixtures
- Mocking and fakes (MockProvider)
- Performance benchmarks
- Coverage reporting (85%+ target)
- CI/CD integration

**When to Read:** Writing tests, debugging test failures, setting up CI/CD, performance benchmarking

---

#### 📅 [Weekday Master System](WEEKDAY_MASTER_COMPLETE_GUIDE.md) (1,000+ lines)
Complete guide for historical data aggregation.

**Topics Covered:**
- Batch generator (historical processing)
- Real-time builder (live market updates)
- EOD updater (automated daily execution)
- Task Scheduler automation (Windows)
- Quality reporting and validation
- File format specifications

**When to Read:** Backtesting setup, historical data processing, automated daily aggregation

---

### Module Guides Index

📖 **[MODULE_GUIDES_INDEX.md](MODULE_GUIDES_INDEX.md)** - Central navigation hub for all module guides with cross-references and quick start by role (analyst, developer, devops, trader).

---

## 4. Reference Documentation

### Complete Reference Catalogs

#### Environment Variables

| Document | Description | Link |
|----------|-------------|------|
| **ENV_FLAGS_TABLES.md** | Complete catalog of 200+ environment variables with types, defaults, descriptions | [View](../ENV_FLAGS_TABLES.md) |
| **ENV_VARS_CATALOG.md** | Auto-generated environment variables catalog with usage examples | [View](ENV_VARS_CATALOG.md) |
| **ENV_VARS_AUTO.md** | Machine-readable environment variables (JSON format) | [View](ENV_VARS_AUTO.md) |
| **ENV_LIFECYCLE.md** | Environment variable lifecycle management and deprecation policy | [View](ENV_LIFECYCLE.md) |

**Quick Reference - Key Environment Variables:**

```bash
# Core Platform
G6_ENV=development              # Environment (dev/staging/prod)
G6_LOG_LEVEL=INFO              # Logging level
G6_DATA_DIR=data               # Base data directory

# Metrics & Monitoring
G6_METRICS_ENABLED=1           # Enable Prometheus metrics
G6_METRICS_PORT=9108           # Metrics server port
G6_ENABLE_METRIC_GROUPS=       # Allowlist metric groups (comma-separated)
G6_DISABLE_METRIC_GROUPS=      # Blocklist metric groups (comma-separated)

# Collection
G6_COLLECTION_INTERVAL=60      # Collection cycle interval (seconds)
G6_PROVIDER=kite_live          # Primary provider (kite_live/mock/synthetic)
G6_MARKET_HOURS_GATING=1       # Enable market hours check

# Storage
G6_CSV_DIR=data/g6_data        # CSV storage directory
G6_INFLUX_ENABLED=0            # Enable InfluxDB
G6_INFLUX_URL=http://localhost:8086  # InfluxDB URL

# Authentication
KITE_API_KEY=                  # Kite Connect API key
KITE_ACCESS_TOKEN=             # Kite Connect access token

# Analytics
G6_ENABLE_GREEKS=1             # Enable Greeks calculation
G6_ENABLE_IV=1                 # Enable IV solver
G6_VOL_SURFACE=0               # Enable vol surface (high cardinality)

# Feature Toggles
G6_ENABLE_PANELS=1             # Enable panel generation
G6_ENABLE_SSE=0                # Enable SSE streaming
G6_ADAPTIVE_CONTROLLER=0       # Enable adaptive controller (experimental)
```

---

#### Prometheus Metrics

| Document | Description | Link |
|----------|-------------|------|
| **METRICS_CATALOG.md** | Complete catalog of 145+ Prometheus metrics with types, labels, cardinality, example queries | [View](METRICS_CATALOG.md) |
| **METRICS_GOVERNANCE.md** | Cardinality governance policies and best practices | [View](../METRICS_GOVERNANCE.md) |
| **METRICS_USAGE.md** | Metrics usage patterns and integration examples | [View](METRICS_USAGE.md) |
| **metrics_spec.yaml** | Machine-readable metrics specification (YAML format) | [View](metrics_spec.yaml) |

**Quick Reference - Key Metrics:**

```promql
# Collection Performance
rate(g6_collection_cycles[5m])                    # Collection cycle rate
g6:collection_success_rate:5m                     # Success rate (5m window)
histogram_quantile(0.9, rate(g6_collection_duration_seconds_bucket[5m]))  # P90 duration

# Analytics
rate(g6_iv_estimation_success[5m])                # IV success rate
rate(g6_iv_estimation_failure[5m])                # IV failure rate
avg by (index) (g6_vol_surface_quality_score)     # Vol surface quality

# Storage
histogram_quantile(0.9, rate(g6_csv_write_seconds_bucket[5m]))  # CSV write P90
rate(g6_influx_points_written[5m])                # InfluxDB write rate

# Provider Health
g6_provider_mode                                   # Current provider (one-hot gauge)
rate(g6_collection_errors[5m])                    # Error rate by index

# Resource Usage
process_cpu_seconds_total                          # CPU usage
process_resident_memory_bytes                      # Memory usage
```

---

#### Configuration Files

| Document | Description | Link |
|----------|-------------|------|
| **CONFIG_KEYS_CATALOG.md** | Complete catalog of configuration keys with schemas | [View](CONFIG_KEYS_CATALOG.md) |
| **CONFIG_FEATURE_TOGGLES.md** | Feature toggle reference and patterns | [View](CONFIG_FEATURE_TOGGLES.md) |
| **CONFIGURATION.md** | Configuration system architecture and design | [View](CONFIGURATION.md) |

---

#### Architecture & Design

| Document | Description | Link |
|----------|-------------|------|
| **ARCHITECTURE.md** | Platform architecture overview and design decisions | [View](ARCHITECTURE.md) |
| **UNIFIED_MODEL.md** | Unified data model specification | [View](UNIFIED_MODEL.md) |
| **OBSERVABILITY_DASHBOARDS.md** | Grafana dashboard specifications | [View](OBSERVABILITY_DASHBOARDS.md) |
| **PARALLEL_COLLECTION.md** | Parallel collection design (future enhancement) | [View](PARALLEL_COLLECTION.md) |
| **SSE_ARCHITECTURE.md** | Server-Sent Events (SSE) streaming architecture | [View](SSE_ARCHITECTURE.md) |

---

#### Operational Guides

| Document | Description | Link |
|----------|-------------|------|
| **RETENTION_POLICY.md** | Data retention policies and archival procedures | [View](RETENTION_POLICY.md) |
| **ERROR_HANDLING.md** | Error handling patterns and recovery procedures | [View](ERROR_HANDLING.md) |
| **GOVERNANCE.md** | Platform governance policies and standards | [View](GOVERNANCE.md) |
| **DEPRECATIONS.md** | Deprecated features and migration paths | [View](DEPRECATIONS.md) |

---

## 5. Quick Reference

### Common Commands

```bash
# Platform Startup
python -m src.main                                 # Start platform (live mode)
python -m src.main --config config/custom.json    # Custom config
export G6_PROVIDER=mock && python -m src.main     # Mock mode

# Summary & Monitoring
python -m scripts.summary.app                     # Rich terminal UI
python -m scripts.summary.app --no-rich           # Plain text mode
python -m scripts.summary.app --refresh 0.5       # Fast refresh

# Token Management
python -m src.tools.token_manager                 # Interactive token acquisition

# Testing
pytest                                             # Run all tests
pytest -m smoke                                    # Smoke tests only
pytest -n auto                                     # Parallel execution
pytest --cov=src --cov-report=html                # Coverage report

# Weekday Master
python scripts/eod_weekday_master.py --help       # EOD batch generator
python scripts/weekday_master_rt_builder.py       # Real-time builder

# Data Tools
python scripts/dev_tools.py summary               # Status summary
python scripts/dev_tools.py simulate-status       # Simulate status file
```

### VS Code Tasks

```bash
# Quick Launch
G6: Init Menu                                      # Interactive launcher

# Collection & Simulation
Smoke: Start Simulator                             # Generate test data
Smoke: Summary Demo                                # View summary

# Testing
pytest: two-phase (parallel -> serial)            # Full test suite
pytest - fast inner loop                          # Quick tests only

# Observability
Observability: Start baseline                      # Prometheus + Grafana
G6: Restart + Open Analytics (Infinity)           # Grafana dashboard
Metrics: Start 9108                               # Metrics server

# Weekday Master
Overlays: Generate weekday master (today)         # Generate today's data
Metrics: Start overlay exporter (9109)            # Start overlay exporter
```

### File Locations

```bash
# Configuration
config/platform_config.json                        # Main config
config/indices_config.json                         # Index settings
.kite_token                                        # Auth token (gitignored)

# Data
data/runtime_status.json                           # Current status
data/g6_data/options/                             # CSV storage
data/panels/                                       # Panel JSON artifacts
data/weekday_master/                              # Weekday master files

# Logs
logs/g6_platform.log                              # Application logs

# Metrics & Dashboards
http://localhost:9108/metrics                      # Prometheus metrics
http://localhost:9090                              # Prometheus UI
http://localhost:3002                              # Grafana UI

# Generated Reports
htmlcov/index.html                                # Coverage report
```

---

## 6. Use Cases & Workflows

### Use Case 1: Analyst - Backtesting Setup

**Goal:** Set up historical data for backtesting strategies.

**Steps:**

1. **Generate Weekday Master Files**
   ```bash
   # Generate historical aggregates
   python scripts/eod_weekday_master.py \
     --base-dir data/g6_data \
     --output-dir data/weekday_master \
     --all
   ```

2. **Verify Data Quality**
   ```bash
   # Check quality report
   cat data/weekday_master/quality_report.json
   ```

3. **Access Data in Python**
   ```python
   import pandas as pd
   
   # Load weekday master
   df = pd.read_csv('data/weekday_master/NIFTY/weekday_master.csv')
   
   # Filter expiry
   expiry_data = df[df['expiry'] == '2025-01-30']
   
   # Calculate signals
   pcr = expiry_data['put_oi'].sum() / expiry_data['call_oi'].sum()
   ```

**Reference Guides:**
- [Weekday Master Guide](WEEKDAY_MASTER_COMPLETE_GUIDE.md)
- [Storage Guide](STORAGE_GUIDE.md)

---

### Use Case 2: Developer - Add New Analytics

**Goal:** Implement custom analytics metric (e.g., Max Pain strike).

**Steps:**

1. **Add Analytics Function**
   ```python
   # src/analytics/option_chain.py
   def calculate_max_pain(option_chain: pd.DataFrame) -> float:
       """Calculate Max Pain strike."""
       # Implementation
       return max_pain_strike
   ```

2. **Add Tests**
   ```python
   # tests/test_analytics/test_option_chain.py
   def test_calculate_max_pain():
       chain = create_sample_chain()
       max_pain = calculate_max_pain(chain)
       assert 24000 <= max_pain <= 25000
   ```

3. **Add Metric**
   ```python
   # src/metrics/metrics.py
   self._maybe_register(
       group='analytics',
       attr='max_pain_strike',
       metric_cls=Gauge,
       name='g6_max_pain_strike',
       documentation='Max Pain strike price',
       labels=['index', 'expiry']
   )
   ```

4. **Emit Metric**
   ```python
   max_pain = calculate_max_pain(chain)
   metrics.max_pain_strike.labels(index="NIFTY", expiry=expiry).set(max_pain)
   ```

5. **Create Grafana Panel**
   ```json
   {
     "title": "Max Pain Strike",
     "targets": [{
       "expr": "g6_max_pain_strike{index=\"NIFTY\"}"
     }]
   }
   ```

**Reference Guides:**
- [Analytics Guide](ANALYTICS_GUIDE.md)
- [Metrics Guide](METRICS_GUIDE.md)
- [Testing Guide](TESTING_GUIDE.md)

---

### Use Case 3: DevOps - Production Deployment

**Goal:** Deploy G6 Platform to production with monitoring.

**Steps:**

1. **Set Up Environment**
   ```bash
   # Production env vars
   export G6_ENV=production
   export G6_LOG_LEVEL=INFO
   export G6_PROVIDER=kite_live
   export KITE_API_KEY=prod_api_key
   export KITE_ACCESS_TOKEN=prod_token
   ```

2. **Configure InfluxDB**
   ```bash
   export G6_INFLUX_ENABLED=1
   export G6_INFLUX_URL=http://influxdb.prod:8086
   export G6_INFLUX_TOKEN=prod_influx_token
   export G6_INFLUX_ORG=g6platform
   export G6_INFLUX_BUCKET=g6_prod
   ```

3. **Set Up Prometheus**
   ```yaml
   # prometheus.yml
   scrape_configs:
     - job_name: 'g6_production'
       static_configs:
         - targets: ['g6-prod-1:9108', 'g6-prod-2:9108']
       scrape_interval: 15s
   ```

4. **Configure Alerting**
   ```yaml
   # prometheus_alerts.yml
   - alert: CollectionFailureRateHigh
     expr: g6:collection_success_rate:5m < 0.95
     for: 5m
     annotations:
       summary: "Production collection failing"
   ```

5. **Deploy Platform**
   ```bash
   # Docker deployment example
   docker-compose up -d g6-platform
   docker-compose up -d prometheus
   docker-compose up -d grafana
   ```

6. **Verify Health**
   ```bash
   # Check metrics endpoint
   curl http://g6-prod-1:9108/metrics
   
   # Check status file
   curl http://g6-prod-1:8080/api/status
   ```

**Reference Guides:**
- [Configuration Guide](CONFIGURATION_GUIDE.md)
- [Metrics Guide](METRICS_GUIDE.md)
- [Storage Guide](STORAGE_GUIDE.md)
- [Auth Guide](AUTH_GUIDE.md)

---

### Use Case 4: Trader - Live Monitoring

**Goal:** Monitor real-time market data and alerts.

**Steps:**

1. **Start Platform (Live Mode)**
   ```bash
   # Ensure token is valid
   python -m src.tools.token_manager
   
   # Start collection
   python -m src.main
   ```

2. **Launch Terminal Dashboard**
   ```bash
   # Rich terminal UI with live updates
   python -m scripts.summary.app --refresh 0.5
   ```

3. **Monitor in Browser (SSE)**
   ```bash
   # Enable SSE streaming
   export G6_ENABLE_SSE=1
   export G6_SSE_PORT=9315
   
   # Access browser dashboard
   open http://localhost:9315/dashboard.html
   ```

4. **Set Up Alerts**
   ```yaml
   # Custom alerts for trading signals
   - alert: PCRExtreme
     expr: g6_put_call_ratio > 1.5 or g6_put_call_ratio < 0.5
     annotations:
       summary: "PCR at extreme level"
   ```

5. **Access Grafana Dashboards**
   ```bash
   # Open analytics dashboard
   open http://localhost:3002/d/g6-analytics
   ```

**Reference Guides:**
- [Panels Guide](PANELS_GUIDE.md)
- [Collector System Guide](COLLECTOR_SYSTEM_GUIDE.md)
- [Analytics Guide](ANALYTICS_GUIDE.md)

---

## 7. Troubleshooting

### Common Issues

#### Platform Won't Start

**Symptom:** `ModuleNotFoundError` or import errors

**Solutions:**
```bash
# 1. Check Python version
python --version  # Must be 3.10+

# 2. Reinstall dependencies
pip install -r requirements.txt

# 3. Check PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

**Reference:** [Configuration Guide - Troubleshooting](CONFIGURATION_GUIDE.md#8-troubleshooting)

---

#### Authentication Failing

**Symptom:** `Token is invalid or has expired`

**Solutions:**
```bash
# 1. Regenerate token
python -m src.tools.token_manager

# 2. Check token file
cat .kite_token

# 3. Verify API credentials
echo $KITE_API_KEY
echo $KITE_API_SECRET

# 4. Test with mock provider
export G6_PROVIDER=mock
python -m src.main
```

**Reference:** [Auth Guide - Troubleshooting](AUTH_GUIDE.md#8-troubleshooting)

---

#### High Memory Usage

**Symptom:** Process memory > 2GB

**Solutions:**
```bash
# 1. Disable high-cardinality metrics
export G6_DISABLE_METRIC_GROUPS="analytics_vol_surface,options_detail"

# 2. Reduce collection frequency
export G6_COLLECTION_INTERVAL=120  # 2 minutes instead of 1

# 3. Enable data pruning
export G6_CSV_RETENTION_DAYS=7

# 4. Monitor Prometheus cardinality
curl http://localhost:9090/api/v1/label/__name__/values
```

**Reference:** [Metrics Guide - Cardinality Management](METRICS_GUIDE.md#4-cardinality-management)

---

#### Tests Failing

**Symptom:** Tests pass locally but fail in CI

**Solutions:**
```bash
# 1. Run with same pytest config
pytest --strict-markers

# 2. Check for serial tests
pytest -m serial -n 0

# 3. Reset metrics registry
pytest --forked

# 4. Check environment isolation
pytest --capture=no -v
```

**Reference:** [Testing Guide - Troubleshooting](TESTING_GUIDE.md#9-troubleshooting)

---

#### Data Not Collected

**Symptom:** Empty CSV files or no data in storage

**Solutions:**
```bash
# 1. Check provider status
cat data/runtime_status.json | jq '.provider'

# 2. Verify market hours
python -c "from src.utils.market_hours import is_market_open; print(is_market_open())"

# 3. Check collection errors
curl http://localhost:9108/metrics | grep collection_errors

# 4. Enable debug logging
export G6_LOG_LEVEL=DEBUG
python -m src.main
```

**Reference:** [Collector System Guide - Troubleshooting](COLLECTOR_SYSTEM_GUIDE.md#7-monitoring--troubleshooting)

---

### Getting Help

1. **Check Module Guides** - Comprehensive troubleshooting sections in each guide
2. **Search Issues** - GitHub issue tracker
3. **Review Logs** - `logs/g6_platform.log`
4. **Check Metrics** - Prometheus metrics often reveal root cause
5. **Run Diagnostics**:
   ```bash
   python scripts/dev_tools.py diagnose
   ```

---

## 8. Contributing

### Development Setup

```bash
# 1. Fork and clone
git clone https://github.com/yourusername/g6_reorganized.git
cd g6_reorganized

# 2. Create feature branch
git checkout -b feature/my-new-feature

# 3. Install dev dependencies
pip install -r requirements-dev.txt

# 4. Install pre-commit hooks
pre-commit install

# 5. Make changes and test
pytest
ruff check src scripts
mypy src

# 6. Commit and push
git add .
git commit -m "feat: add new feature"
git push origin feature/my-new-feature
```

### Code Quality Standards

- **Test Coverage**: 85%+ line coverage required
- **Type Hints**: All public functions must have type hints
- **Documentation**: Docstrings for all classes and public methods
- **Linting**: Must pass `ruff check` and `mypy` checks
- **Tests**: Add tests for all new features

### Documentation Updates

When adding new features:

1. **Update Module Guide** - Add to relevant guide (e.g., ANALYTICS_GUIDE.md)
2. **Update Reference Docs** - Add to ENV_FLAGS_TABLES.md or METRICS_CATALOG.md
3. **Add Examples** - Include complete workflow examples
4. **Update This Guide** - Add to use cases if applicable

### Pull Request Process

1. Ensure all tests pass
2. Update documentation
3. Add changelog entry
4. Request review from maintainers
5. Address review comments
6. Squash commits before merge

---

## 📖 Additional Resources

### Project Documentation

- [README.md](../README.md) - Project overview and quick start
- [ARCHITECTURE.md](ARCHITECTURE.md) - Detailed architecture documentation
- [GOVERNANCE.md](GOVERNANCE.md) - Project governance and policies
- [DEPRECATIONS.md](DEPRECATIONS.md) - Deprecated features

### External Links

- **Kite Connect API**: https://kite.trade/docs/connect/v3/
- **Prometheus Documentation**: https://prometheus.io/docs/
- **Grafana Documentation**: https://grafana.com/docs/
- **pytest Documentation**: https://docs.pytest.org/

---

## 📝 License

See [LICENSE](../LICENSE) file for details.

---

## 🙏 Acknowledgments

- Kite Connect API for market data
- Prometheus for metrics infrastructure
- Grafana for visualization
- Rich library for terminal UI

---

**Last Updated:** January 25, 2025  
**Version:** 1.0  
**Total Documentation:** 12,600+ lines across 9 module guides

---

**Navigation:**
- [← Back to Module Guides Index](MODULE_GUIDES_INDEX.md)
- [→ Getting Started Guide](#2-getting-started)
- [→ Module Guides](#3-module-guides)
- [→ Reference Documentation](#4-reference-documentation)
