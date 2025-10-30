# G6 Platform - Metrics & Monitoring Guide

**Complete User Guide for Prometheus Metrics System**

---

## Table of Contents

1. [Overview](#1-overview)
2. [Metrics Registry](#2-metrics-registry)
3. [Metric Groups & Gating](#3-metric-groups--gating)
4. [Cardinality Management](#4-cardinality-management)
5. [Grafana Integration](#5-grafana-integration)
6. [Recording Rules & Alerts](#6-recording-rules--alerts)
7. [Complete Workflows](#7-complete-workflows)
8. [Configuration Reference](#8-configuration-reference)
9. [Monitoring & Troubleshooting](#9-monitoring--troubleshooting)
10. [Best Practices](#10-best-practices)
11. [Integration Examples](#11-integration-examples)
12. [Summary](#12-summary)

---

## 1. Overview

### What is the Metrics System?

The G6 Metrics System provides **comprehensive observability** for the options trading platform using **Prometheus** as the time-series metrics backend. It tracks:

- **Collection performance**: Cycle duration, error rates, success rates
- **Option data**: Prices, IV, Greeks, volume, open interest
- **Analytics**: Vol surface quality, risk aggregation, market breadth
- **Storage**: Write latency, batch sizes, retention metrics
- **Caching**: Hit ratios, evictions, cache sizes
- **Provider health**: Failover events, rate limiting, API errors

### Key Features

✅ **145+ metrics** across 17+ metric groups  
✅ **Declarative registration** with spec-based generation  
✅ **Group-based gating** for selective metric enable/disable  
✅ **Cardinality controls** to prevent label explosion  
✅ **Prometheus exporter** on port 9108 (configurable)  
✅ **Grafana dashboards** for visualization  
✅ **Recording rules** for aggregated metrics  
✅ **Alert rules** for SLA monitoring  

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    G6 Application Code                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Collectors  │  │  Analytics   │  │   Storage    │      │
│  │              │  │              │  │              │      │
│  │  metrics.    │  │  metrics.    │  │  metrics.    │      │
│  │  collection_ │  │  iv_success  │  │  csv_write   │      │
│  │  cycles.inc()│  │  .inc()      │  │  _seconds    │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            │                                 │
│                    ┌───────▼────────┐                        │
│                    │ MetricsRegistry │                       │
│                    │  (singleton)    │                       │
│                    │                 │                       │
│                    │ - Counter       │                       │
│                    │ - Gauge         │                       │
│                    │ - Histogram     │                       │
│                    │ - Summary       │                       │
│                    └───────┬─────────┘                       │
│                            │                                 │
│                    ┌───────▼─────────┐                       │
│                    │ Group Filters   │                       │
│                    │ (enable/disable)│                       │
│                    └───────┬─────────┘                       │
└────────────────────────────┼─────────────────────────────────┘
                             │
                             │ HTTP :9108/metrics
                             │
                    ┌────────▼─────────┐
                    │   Prometheus     │
                    │   (scrape every  │
                    │    15s default)  │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Grafana        │
                    │   (dashboards)   │
                    └──────────────────┘
```

### File Structure

```
src/metrics/
├── __init__.py              # Facade exports
├── metrics.py               # MetricsRegistry singleton (1,600 lines)
├── groups.py                # MetricGroup enum, GroupFilters
├── gating.py                # Conditional metric registration
├── registration.py          # Core registration logic
├── spec.py                  # Declarative metric specifications
├── labels.py                # MetricLabel enum
├── emitter.py               # MetricBatcher for batch emission
├── emission_batcher.py      # EmissionBatcher (advanced batching)
├── cardinality_manager.py   # Label cardinality controls
├── server.py                # Prometheus HTTP server
├── circuit_metrics.py       # Circuit breaker metrics
├── fault_budget.py          # SLA fault budget tracking
└── panels_integrity.py      # Panel integrity check metrics

scripts/
├── start_metrics_server.py  # Standalone metrics server
└── dev_tools.py             # Metrics inspection CLI

docs/
├── METRICS_CATALOG.md       # Auto-generated metric catalog
├── METRICS_GOVERNANCE.md    # Cardinality governance
└── OBSERVABILITY_DASHBOARDS.md  # Dashboard docs

prometheus.yml               # Prometheus config
prometheus_rules.yml         # Recording/alert rules
alertmanager.yml            # Alertmanager config
```

---

## 2. Metrics Registry

### MetricsRegistry Class

**Location**: `src/metrics/metrics.py`

The **singleton registry** that holds all Prometheus metric objects.

#### Key Methods

```python
from src.metrics import get_metrics_registry

# Get singleton instance
metrics = get_metrics_registry()

# Access metrics
metrics.collection_cycles.inc()  # Counter
metrics.index_price.labels(index="NIFTY").set(24500)  # Gauge
metrics.collection_duration.observe(1.234)  # Histogram/Summary
```

#### Metric Types

| Type | Description | Methods | Use Case |
|------|-------------|---------|----------|
| **Counter** | Monotonically increasing | `.inc(value=1)` | Event counts (cycles, errors) |
| **Gauge** | Arbitrary value up/down | `.set(value)`, `.inc()`, `.dec()` | Current state (price, cache size) |
| **Histogram** | Distribution with buckets | `.observe(value)` | Latency, duration |
| **Summary** | Quantiles without buckets | `.observe(value)` | Duration percentiles |

#### Registration Pattern

Metrics are registered **once** at initialization:

```python
class MetricsRegistry:
    def __init__(self):
        # Core platform metrics (always registered)
        self.collection_cycles = Counter(
            'g6_collection_cycles',
            'Number of collection cycles run'
        )
        
        self.index_price = Gauge(
            'g6_index_price',
            'Current index price',
            ['index']  # Label
        )
        
        self.collection_duration = Summary(
            'g6_collection_duration_seconds',
            'Time spent collecting data'
        )
        
        # Conditional registration via groups
        self._maybe_register(
            group='greeks',
            attr='iv_success',
            metric_cls=Counter,
            name='g6_iv_estimation_success',
            documentation='Successful IV estimations',
            labels=['index', 'expiry']
        )
```

#### Singleton Pattern

The registry is a **process-level singleton**:

```python
# First call creates registry
metrics = get_metrics_registry()

# Subsequent calls return same instance
metrics2 = get_metrics_registry()
assert metrics is metrics2
```

**Why Singleton?**
- Prometheus client library enforces unique metric names
- Duplicate registration raises `ValueError`
- Single source of truth for all metrics

---

## 3. Metric Groups & Gating

### MetricGroup Enum

**Location**: `src/metrics/groups.py`

Groups organize related metrics and enable **selective registration**.

```python
from enum import Enum

class MetricGroup(str, Enum):
    ANALYTICS_VOL_SURFACE = "analytics_vol_surface"
    ANALYTICS_RISK_AGG = "analytics_risk_agg"
    PANEL_DIFF = "panel_diff"
    PARALLEL = "parallel"
    SLA_HEALTH = "sla_health"
    OVERLAY_QUALITY = "overlay_quality"
    STORAGE = "storage"
    CACHE = "cache"
    EXPIRY_POLICY = "expiry_policy"
    PANELS_INTEGRITY = "panels_integrity"
    IV_ESTIMATION = "iv_estimation"
    GREEKS = "greeks"
    ADAPTIVE_CONTROLLER = "adaptive_controller"
    PROVIDER_FAILOVER = "provider_failover"
    EXPIRY_REMEDIATION = "expiry_remediation"
    LIFECYCLE = "lifecycle"
    SSE_INGEST = "sse_ingest"
```

### Group-Based Gating

#### Enable Specific Groups

```bash
# Only enable analytics metrics
export G6_ENABLE_METRIC_GROUPS="greeks,analytics_vol_surface"

# Start platform - only these groups registered
python -m src.main
```

#### Disable Specific Groups

```bash
# Disable high-cardinality vol surface per-expiry metrics
export G6_DISABLE_METRIC_GROUPS="analytics_vol_surface"

# Start platform - all groups except vol_surface
python -m src.main
```

#### Always-On Groups

Some groups **cannot be disabled** (critical for platform health):

```python
ALWAYS_ON = {
    MetricGroup.EXPIRY_REMEDIATION,  # Expiry correction lifecycle
    MetricGroup.PROVIDER_FAILOVER,   # Provider resilience
    MetricGroup.IV_ESTIMATION,       # IV solver metrics
    MetricGroup.SLA_HEALTH,          # SLA breach detection
}
```

### GroupFilters Class

**Location**: `src/metrics/groups.py`

```python
from src.metrics.groups import load_group_filters

filters = load_group_filters()

# Check if metric group is allowed
if filters.allowed('greeks'):
    metrics.iv_success.labels(index="NIFTY", expiry="2025-01-30").inc()
```

**Filter Logic:**

1. If `enabled_raw` is set → only those groups allowed
2. If `disabled_raw` contains group → group blocked
3. Otherwise → group allowed

---

## 4. Cardinality Management

### What is Cardinality?

**Cardinality** = unique label combinations for a metric.

High cardinality example:
```python
# BAD: strike × expiry × index × type = 100 × 5 × 4 × 2 = 4,000 series
metrics.option_price.labels(
    index="NIFTY",
    expiry="2025-01-30",
    strike="24500",
    type="CE"
).set(123.45)
```

### Cardinality Levels

| Level | Series Count | Description |
|-------|--------------|-------------|
| **low** | < 10 | No labels or single low-card label |
| **low-moderate** | 10-100 | Index-level metrics (4-6 indices) |
| **moderate** | 100-1,000 | Index × expiry (4 × 5 = 20) |
| **high** | 1,000-10,000 | Per-expiry detailed metrics |
| **very_high** | > 10,000 | Per-strike option metrics (avoid!) |

### Cardinality Controls

#### 1. Group-Based Gating

Disable entire high-cardinality groups:

```bash
# Disable per-expiry vol surface metrics (high cardinality)
export G6_DISABLE_METRIC_GROUPS="analytics_vol_surface"
```

#### 2. Conditional Registration

```python
# Only register if env var set
if os.getenv('G6_VOL_SURFACE_PER_EXPIRY') == '1':
    metrics._maybe_register(
        group='analytics_vol_surface',
        attr='vol_surface_rows_expiry',
        metric_cls=Gauge,
        name='g6_vol_surface_rows_expiry',
        documentation='Vol surface per-expiry row count by source',
        labels=['index', 'expiry', 'source']  # High cardinality!
    )
```

#### 3. Aggregation at Query Time

Instead of per-strike metrics, use **recording rules**:

```yaml
# prometheus_rules.yml
groups:
  - name: aggregations
    interval: 15s
    rules:
      # Aggregate per-strike option prices to per-expiry avg
      - record: g6:option_price_avg:by_expiry
        expr: |
          avg by (index, expiry, type) (g6_option_price)
```

#### 4. TTL & Cleanup

Prometheus automatically removes stale series after `--storage.tsdb.retention.time` (default 15 days).

---

## 5. Grafana Integration

### Dashboard Generation

**Location**: `scripts/grafana_dashboard_generator.py`

Generate dashboards from metric specs:

```bash
# Generate all dashboards
python scripts/grafana_dashboard_generator.py

# Output: grafana_provisioning/dashboards/*.json
```

### Dashboard Structure

```
grafana_provisioning/
├── dashboards/
│   ├── g6-analytics.json      # Analytics metrics dashboard
│   ├── g6-collection.json     # Collection pipeline dashboard
│   ├── g6-storage.json        # Storage & persistence dashboard
│   └── g6-overview.json       # High-level overview
└── datasources/
    └── prometheus.yml         # Prometheus datasource config
```

### Key Dashboards

#### 1. Collection Pipeline (`g6-collection.json`)

**Panels:**
- Collection cycle rate: `rate(g6_collection_cycles[5m])`
- Cycle duration p90: `histogram_quantile(0.9, rate(g6_collection_duration_seconds_bucket[5m]))`
- Error rate: `rate(g6_collection_errors[5m])`
- Success rate: `rate(g6_pipeline_cycles_success_total[5m]) / rate(g6_pipeline_cycles_total[5m])`

#### 2. Analytics Dashboard (`g6-analytics.json`)

**Panels:**
- IV success rate: `rate(g6_iv_estimation_success[5m])`
- IV failure rate: `rate(g6_iv_estimation_failure[5m])`
- Greeks computation: `rate(g6_greeks_computed[5m])`
- Vol surface quality: `avg by (index) (g6_vol_surface_quality_score)`

#### 3. Storage Dashboard (`g6-storage.json`)

**Panels:**
- CSV write latency: `histogram_quantile(0.9, rate(g6_csv_write_seconds_bucket[5m]))`
- InfluxDB write rate: `rate(g6_influx_points_written[5m])`
- Batch buffer size: `avg(g6_csv_batch_size)`
- Storage errors: `rate(g6_storage_errors[5m])`

### Grafana Provisioning

**Location**: `C:/GrafanaData/conf/grafana.ini`

```ini
[paths]
data = C:/GrafanaData/data
logs = C:/GrafanaData/logs
plugins = C:/GrafanaData/plugins
provisioning = C:/GrafanaData/provisioning

[server]
http_port = 3002
protocol = http

[auth.anonymous]
enabled = true
org_role = Editor

[security]
admin_user = admin
admin_password = admin
```

**Auto-provision datasource:**

`C:/GrafanaData/provisioning/datasources/prometheus.yml`
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://localhost:9090
    isDefault: true
    editable: true
```

---

## 6. Recording Rules & Alerts

### Recording Rules

**Location**: `prometheus_rules.yml`

Pre-compute expensive queries for dashboard performance.

```yaml
groups:
  - name: g6_aggregations
    interval: 15s
    rules:
      # Per-index option count
      - record: g6:options_count:by_index
        expr: sum by (index) (g6_options_collected)
      
      # Collection success rate (5m window)
      - record: g6:collection_success_rate:5m
        expr: |
          rate(g6_pipeline_cycles_success_total[5m])
          /
          rate(g6_pipeline_cycles_total[5m])
      
      # IV success rate by index
      - record: g6:iv_success_rate:by_index
        expr: |
          sum by (index) (rate(g6_iv_estimation_success[5m]))
          /
          sum by (index) (
            rate(g6_iv_estimation_success[5m])
            + rate(g6_iv_estimation_failure[5m])
          )
      
      # Average cycle duration (5m)
      - record: g6:cycle_duration_avg:5m
        expr: |
          rate(g6_collection_duration_seconds_sum[5m])
          /
          rate(g6_collection_duration_seconds_count[5m])
```

### Alert Rules

**Location**: `prometheus_alerts.yml`

Define SLA breach alerts:

```yaml
groups:
  - name: g6_sla_alerts
    interval: 15s
    rules:
      # Alert if collection success rate < 95%
      - alert: CollectionSuccessRateLow
        expr: g6:collection_success_rate:5m < 0.95
        for: 5m
        labels:
          severity: warning
          component: collection
        annotations:
          summary: "Collection success rate below 95%"
          description: "Current rate: {{ $value | humanizePercentage }}"
      
      # Alert if cycle duration > 60s
      - alert: CollectionCycleSlow
        expr: g6:cycle_duration_avg:5m > 60
        for: 2m
        labels:
          severity: warning
          component: collection
        annotations:
          summary: "Collection cycle duration exceeds 60s"
          description: "Current avg: {{ $value | humanizeDuration }}"
      
      # Alert if IV failure rate > 10%
      - alert: IVEstimationFailureHigh
        expr: |
          sum(rate(g6_iv_estimation_failure[5m]))
          /
          sum(rate(g6_iv_estimation_success[5m]) + rate(g6_iv_estimation_failure[5m]))
          > 0.1
        for: 5m
        labels:
          severity: warning
          component: analytics
        annotations:
          summary: "IV estimation failure rate above 10%"
          description: "Current rate: {{ $value | humanizePercentage }}"
      
      # Alert if Prometheus scrape failing
      - alert: MetricsScrapeFailing
        expr: up{job="g6_platform"} == 0
        for: 1m
        labels:
          severity: critical
          component: metrics
        annotations:
          summary: "Cannot scrape G6 metrics endpoint"
          description: "Prometheus scrape target down for 1m+"
```

### Alertmanager Configuration

**Location**: `alertmanager.yml`

```yaml
global:
  resolve_timeout: 5m

route:
  receiver: 'default'
  group_by: ['alertname', 'component']
  group_wait: 10s
  group_interval: 30s
  repeat_interval: 1h
  
  routes:
    # Critical alerts route
    - match:
        severity: critical
      receiver: 'critical-alerts'
      continue: false
    
    # Warning alerts route
    - match:
        severity: warning
      receiver: 'warning-alerts'

receivers:
  - name: 'default'
    # Add webhook or email config here
    
  - name: 'critical-alerts'
    # Pager/SMS for critical alerts
    
  - name: 'warning-alerts'
    # Email for warnings
```

---

## 7. Complete Workflows

### Workflow 1: Add New Metric

**Scenario**: Track PCR (Put-Call Ratio) per expiry.

#### Step 1: Choose Metric Type

PCR is a **point-in-time value** → Use `Gauge`

#### Step 2: Define Metric Group

PCR relates to options analytics → Group: `greeks`

#### Step 3: Register Metric

Edit `src/metrics/metrics.py`:

```python
class MetricsRegistry:
    def __init__(self):
        # ... existing metrics ...
        
        # Add PCR metric (conditional on greeks group)
        self._maybe_register(
            group='greeks',
            attr='pcr',
            metric_cls=Gauge,
            name='g6_put_call_ratio',
            documentation='Put-Call Ratio',
            labels=['index', 'expiry']
        )
```

#### Step 4: Emit Metric

In analytics code (`src/analytics/option_chain.py`):

```python
from src.metrics import get_metrics_registry

def calculate_pcr(index: str, expiry: str, calls: int, puts: int) -> float:
    """Calculate Put-Call Ratio."""
    if calls == 0:
        return 0.0
    
    pcr = puts / calls
    
    # Emit metric
    metrics = get_metrics_registry()
    if hasattr(metrics, 'pcr'):
        metrics.pcr.labels(index=index, expiry=expiry).set(pcr)
    
    return pcr
```

#### Step 5: Test Metric

```bash
# Start platform
python -m src.main

# Check metric endpoint
curl http://localhost:9108/metrics | grep g6_put_call_ratio

# Output:
# g6_put_call_ratio{index="NIFTY",expiry="2025-01-30"} 1.23
# g6_put_call_ratio{index="BANKNIFTY",expiry="2025-01-30"} 0.87
```

#### Step 6: Add to Dashboard

Edit `grafana_provisioning/dashboards/g6-analytics.json`:

```json
{
  "panels": [
    {
      "title": "Put-Call Ratio (PCR)",
      "targets": [
        {
          "expr": "g6_put_call_ratio",
          "legendFormat": "{{index}} {{expiry}}"
        }
      ],
      "type": "timeseries"
    }
  ]
}
```

---

### Workflow 2: Debug High Cardinality

**Scenario**: Prometheus memory usage spiking.

#### Step 1: Check Cardinality

Query Prometheus:
```promql
# Count unique series per metric
count by (__name__) ({__name__=~"g6_.*"})
```

**Output:**
```
g6_option_price{...} 45000  # ⚠️ Very high!
g6_option_iv{...} 45000
g6_index_price{...} 4
```

#### Step 2: Identify Culprit

45,000 series for `g6_option_price` → Per-strike × per-expiry × per-index × per-type

#### Step 3: Disable High-Cardinality Group

```bash
# Check which group owns this metric
grep -r "option_price" src/metrics/spec.py

# Output: group="options_detail" (example)

# Disable the group
export G6_DISABLE_METRIC_GROUPS="options_detail"
```

#### Step 4: Restart & Verify

```bash
# Restart platform
python -m src.main

# Check series count again
curl http://localhost:9108/metrics | grep -c "^g6_option_price"

# Should be 0 now
```

#### Step 5: Alternative - Aggregate

Instead of disabling, aggregate at query time:

```yaml
# prometheus_rules.yml
- record: g6:option_price_avg:by_expiry
  expr: avg by (index, expiry, type) (g6_option_price)
```

Now query `g6:option_price_avg:by_expiry` (20 series) instead of `g6_option_price` (45,000 series).

---

### Workflow 3: Set Up Alerting

**Scenario**: Get alerted when collection fails.

#### Step 1: Define Alert Rule

Edit `prometheus_alerts.yml`:

```yaml
groups:
  - name: collection_health
    interval: 15s
    rules:
      - alert: CollectionFailureSpike
        expr: |
          rate(g6_collection_errors[5m]) > 0.1
        for: 3m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Collection error rate elevated"
          description: "Errors: {{ $value | humanize }}/sec"
          runbook_url: "https://wiki/runbook/collection-errors"
```

#### Step 2: Reload Prometheus

```bash
# Send SIGHUP to reload config
curl -X POST http://localhost:9090/-/reload
```

#### Step 3: Configure Alertmanager

Edit `alertmanager.yml`:

```yaml
receivers:
  - name: 'email-platform-team'
    email_configs:
      - to: 'platform-team@example.com'
        from: 'alertmanager@example.com'
        smarthost: 'smtp.example.com:587'
        auth_username: 'alerts'
        auth_password: 'secret'
        headers:
          Subject: '[G6 Alert] {{ .GroupLabels.alertname }}'

route:
  receiver: 'email-platform-team'
  group_by: ['alertname']
  group_wait: 10s
  repeat_interval: 1h
```

#### Step 4: Test Alert

```bash
# Simulate collection errors by killing provider
pkill -9 python

# Wait 3 minutes for alert to fire

# Check Alertmanager
curl http://localhost:9093/api/v2/alerts

# Check email inbox for alert notification
```

---

## 8. Configuration Reference

### Environment Variables

#### Metrics Server

| Variable | Default | Description |
|----------|---------|-------------|
| `G6_METRICS_PORT` | `9108` | Prometheus exporter port |
| `G6_METRICS_HOST` | `0.0.0.0` | Bind address (use `127.0.0.1` for local-only) |
| `G6_METRICS_ENABLED` | `1` | Enable metrics (set to `0` to disable) |

#### Group Gating

| Variable | Default | Description |
|----------|---------|-------------|
| `G6_ENABLE_METRIC_GROUPS` | ` ` | Comma-separated allowlist (empty = all enabled) |
| `G6_DISABLE_METRIC_GROUPS` | ` ` | Comma-separated blocklist |

#### Feature-Specific

| Variable | Default | Description |
|----------|---------|-------------|
| `G6_VOL_SURFACE` | `0` | Enable vol surface metrics |
| `G6_VOL_SURFACE_PER_EXPIRY` | `0` | Enable per-expiry vol surface (high cardinality) |
| `G6_RISK_AGG` | `0` | Enable risk aggregation metrics |
| `G6_ADAPTIVE_CONTROLLER` | `0` | Enable adaptive controller metrics |
| `G6_SSE_INGEST` | `0` | Enable SSE ingest metrics |

#### Logging & Debug

| Variable | Default | Description |
|----------|---------|-------------|
| `G6_QUIET_LOGS` | `0` | Suppress repetitive log lines |
| `G6_METRICS_INIT_SIMPLE_TRACE` | `0` | Log init phase timing |
| `G6_METRICS_PROFILE_INIT` | `0` | Profile init phase performance |
| `G6_METRICS_STRICT_EXCEPTIONS` | `0` | Fail-fast on registration errors |

### Prometheus Configuration

**Location**: `prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: 'g6-production'
    environment: 'prod'

scrape_configs:
  - job_name: 'g6_platform'
    static_configs:
      - targets: ['localhost:9108']
        labels:
          component: 'platform'
    scrape_interval: 15s
    scrape_timeout: 10s

rule_files:
  - 'prometheus_rules.yml'
  - 'prometheus_alerts.yml'

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['localhost:9093']
```

### Grafana Configuration

**Location**: `C:/GrafanaData/conf/grafana.ini`

```ini
[server]
http_port = 3002
protocol = http
domain = localhost
root_url = %(protocol)s://%(domain)s:%(http_port)s/

[auth.anonymous]
enabled = true
org_role = Editor

[dashboards]
default_home_dashboard_path = /var/lib/grafana/dashboards/g6-overview.json
```

---

## 9. Monitoring & Troubleshooting

### Health Checks

#### Metrics Endpoint Reachable?

```bash
curl -I http://localhost:9108/metrics

# Expected: HTTP/1.0 200 OK
```

#### Prometheus Scraping?

Check Prometheus targets:
```
http://localhost:9090/targets
```

**Expected**: `g6_platform` target shows **UP** in green.

#### Grafana Datasource Connected?

Grafana → Configuration → Data Sources → Prometheus → **Test**

**Expected**: "Data source is working"

### Common Issues

#### Issue 1: Metric Not Appearing

**Symptom**: Metric missing from `/metrics` endpoint.

**Causes:**
1. **Group disabled**: Check `G6_DISABLE_METRIC_GROUPS`
2. **Conditional not met**: Check feature flag (e.g., `G6_VOL_SURFACE`)
3. **Never emitted**: Code path not executing

**Debug:**
```bash
# Check registered metrics
curl http://localhost:9108/metrics | grep -i "metric_name"

# Check group filters
python -c "from src.metrics.groups import load_group_filters; f = load_group_filters(); print(f.allowed('your_group'))"

# Enable trace logging
export G6_METRICS_INIT_SIMPLE_TRACE=1
python -m src.main 2>&1 | grep "your_metric"
```

#### Issue 2: High Memory Usage

**Symptom**: Prometheus memory > 2GB, increasing.

**Causes:**
1. **High cardinality**: Too many label combinations
2. **Retention too long**: `--storage.tsdb.retention.time=365d`
3. **Too many samples**: Short scrape interval + high update rate

**Fix:**
```bash
# Check cardinality
curl http://localhost:9090/api/v1/label/__name__/values | jq '.data | length'

# Identify high-cardinality metrics
curl http://localhost:9090/api/v1/query?query=count%20by%20(__name__)%20({__name__=~%22g6_.*%22})

# Disable high-cardinality groups
export G6_DISABLE_METRIC_GROUPS="analytics_vol_surface,options_detail"

# Reduce retention
prometheus --storage.tsdb.retention.time=7d
```

#### Issue 3: Stale Metrics

**Symptom**: Grafana shows data from 5 minutes ago.

**Causes:**
1. **Collection stopped**: Platform crashed
2. **Scrape failing**: Prometheus can't reach `:9108`
3. **Query cache**: Grafana caching old data

**Fix:**
```bash
# Check platform running
ps aux | grep "python.*src.main"

# Check scrape errors
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.health == "down")'

# Force Grafana refresh (Shift + click Refresh button)
```

#### Issue 4: Duplicate Metrics Error

**Symptom**: `ValueError: Duplicated timeseries in CollectorRegistry`

**Causes:**
1. **Multiple registry creations**: Importing metrics twice
2. **Process not cleaned up**: Old process still holding registry
3. **Test isolation issue**: pytest not resetting registry

**Fix:**
```python
# Use singleton pattern
from src.metrics import get_metrics_registry
metrics = get_metrics_registry()

# In tests: reset registry
from prometheus_client import REGISTRY
REGISTRY._collector_to_names.clear()
REGISTRY._names_to_collectors.clear()

# Or use pytest fixture
@pytest.fixture(autouse=True)
def reset_registry():
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
    yield
```

---

## 10. Best Practices

### DO ✅

1. **Use descriptive metric names**
   ```python
   # Good
   metrics.collection_duration_seconds
   
   # Bad
   metrics.time
   ```

2. **Include units in metric names**
   ```python
   # Good
   metrics.csv_write_seconds
   metrics.batch_size_bytes
   
   # Bad
   metrics.write_time
   metrics.batch_size
   ```

3. **Use labels for dimensions**
   ```python
   # Good
   metrics.collection_errors.labels(index="NIFTY", error_type="timeout").inc()
   
   # Bad
   metrics.collection_errors_nifty_timeout.inc()
   ```

4. **Keep cardinality low**
   ```python
   # Good: index (4 values) + expiry (5 values) = 20 series
   metrics.options_collected.labels(index="NIFTY", expiry="2025-01-30")
   
   # Bad: + strike (100 values) = 2000 series
   metrics.options_collected.labels(index="NIFTY", expiry="2025-01-30", strike="24500")
   ```

5. **Use histograms for latency**
   ```python
   # Good
   with metrics.collection_duration.time():
       collect_data()
   
   # Or manual
   start = time.time()
   collect_data()
   metrics.collection_duration.observe(time.time() - start)
   ```

6. **Guard metric access**
   ```python
   # Good: handle missing metrics gracefully
   if hasattr(metrics, 'new_feature_metric'):
       metrics.new_feature_metric.inc()
   
   # Bad: crash if metric disabled
   metrics.new_feature_metric.inc()
   ```

### DON'T ❌

1. **Don't use gauges for counters**
   ```python
   # Bad: loses data on restart
   metrics.requests_total.set(requests_total)
   
   # Good: monotonic, survives restarts
   metrics.requests_total.inc()
   ```

2. **Don't use high-cardinality labels**
   ```python
   # Bad: user_id can be millions of values
   metrics.requests.labels(user_id="12345").inc()
   
   # Good: aggregate by user tier
   metrics.requests.labels(tier="premium").inc()
   ```

3. **Don't create metrics dynamically**
   ```python
   # Bad: creates new metric each call
   def track_metric(name):
       metric = Counter(name, 'desc')
       metric.inc()
   
   # Good: register once at init
   metrics.requests.inc()
   ```

4. **Don't use labels for unrelated data**
   ```python
   # Bad: mixing concerns
   metrics.api_calls.labels(index="NIFTY", user="john", server="prod1").inc()
   
   # Good: separate metrics
   metrics.api_calls.labels(index="NIFTY").inc()
   metrics.user_actions.labels(user="john").inc()
   metrics.server_requests.labels(server="prod1").inc()
   ```

5. **Don't forget to document metrics**
   ```python
   # Bad
   metrics.foo = Counter('foo', 'bar')
   
   # Good
   metrics.collection_cycles = Counter(
       'g6_collection_cycles',
       'Number of collection cycles run. Incremented at the end of each successful cycle.'
   )
   ```

---

## 11. Integration Examples

### Example 1: Integrate with New Module

**Scenario**: Add metrics to a new module `src/risk/portfolio.py`

```python
# src/risk/portfolio.py
from src.metrics import get_metrics_registry
import time

class PortfolioAnalyzer:
    def __init__(self):
        self.metrics = get_metrics_registry()
    
    def analyze_portfolio(self, positions: list) -> dict:
        """Analyze portfolio risk."""
        start = time.time()
        
        try:
            # Perform analysis
            result = self._compute_risk(positions)
            
            # Track success
            if hasattr(self.metrics, 'portfolio_analyses'):
                self.metrics.portfolio_analyses.inc()
            
            # Track duration
            duration = time.time() - start
            if hasattr(self.metrics, 'portfolio_analysis_seconds'):
                self.metrics.portfolio_analysis_seconds.observe(duration)
            
            return result
        
        except Exception as e:
            # Track error
            if hasattr(self.metrics, 'portfolio_errors'):
                self.metrics.portfolio_errors.labels(error_type=type(e).__name__).inc()
            raise
```

**Register metrics** in `src/metrics/metrics.py`:

```python
# In MetricsRegistry.__init__()
self._maybe_register(
    group='risk_analytics',
    attr='portfolio_analyses',
    metric_cls=Counter,
    name='g6_portfolio_analyses_total',
    documentation='Total portfolio analyses performed'
)

self._maybe_register(
    group='risk_analytics',
    attr='portfolio_analysis_seconds',
    metric_cls=Histogram,
    name='g6_portfolio_analysis_seconds',
    documentation='Portfolio analysis duration',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0]
)

self._maybe_register(
    group='risk_analytics',
    attr='portfolio_errors',
    metric_cls=Counter,
    name='g6_portfolio_errors_total',
    documentation='Portfolio analysis errors',
    labels=['error_type']
)
```

---

### Example 2: Metrics in Tests

```python
# tests/test_portfolio.py
import pytest
from src.metrics import get_metrics_registry
from src.risk.portfolio import PortfolioAnalyzer

@pytest.fixture
def metrics():
    """Get metrics registry for testing."""
    return get_metrics_registry()

def test_portfolio_analysis_metrics(metrics):
    """Test that portfolio analysis emits metrics."""
    # Get initial count
    initial = metrics.portfolio_analyses._value._value if hasattr(metrics, 'portfolio_analyses') else 0
    
    # Perform analysis
    analyzer = PortfolioAnalyzer()
    analyzer.analyze_portfolio([...])
    
    # Assert metric incremented
    if hasattr(metrics, 'portfolio_analyses'):
        assert metrics.portfolio_analyses._value._value == initial + 1

def test_portfolio_error_metrics(metrics):
    """Test that errors are tracked."""
    analyzer = PortfolioAnalyzer()
    
    with pytest.raises(ValueError):
        analyzer.analyze_portfolio(invalid_data)
    
    # Check error metric
    if hasattr(metrics, 'portfolio_errors'):
        # Metric should have incremented for ValueError
        error_labels = metrics.portfolio_errors.labels(error_type='ValueError')
        assert error_labels._value._value > 0
```

---

### Example 3: Custom Grafana Panel

**Scenario**: Create panel showing portfolio risk over time.

**Step 1: Define PromQL Query**

```promql
# Average portfolio risk by time window
avg(g6_portfolio_total_risk)

# Risk by portfolio
g6_portfolio_total_risk{portfolio=~"$portfolio"}

# Risk histogram (95th percentile)
histogram_quantile(0.95, rate(g6_portfolio_risk_seconds_bucket[5m]))
```

**Step 2: Create Panel JSON**

```json
{
  "title": "Portfolio Risk",
  "targets": [
    {
      "expr": "g6_portfolio_total_risk{portfolio=~\"$portfolio\"}",
      "legendFormat": "{{portfolio}}",
      "refId": "A"
    }
  ],
  "type": "timeseries",
  "fieldConfig": {
    "defaults": {
      "color": {
        "mode": "palette-classic"
      },
      "unit": "short",
      "decimals": 2
    }
  },
  "options": {
    "legend": {
      "displayMode": "table",
      "placement": "right",
      "calcs": ["lastNotNull", "mean"]
    }
  }
}
```

**Step 3: Add to Dashboard**

Copy JSON to `grafana_provisioning/dashboards/g6-risk.json`

**Step 4: Reload Grafana**

```bash
# Restart Grafana to pick up new dashboard
Restart-Service Grafana -Force
```

---

## 12. Summary

### Quick Start

```bash
# 1. Start metrics server standalone
python scripts/start_metrics_server.py --port 9108

# 2. Check metrics endpoint
curl http://localhost:9108/metrics

# 3. Start Prometheus
prometheus --config.file=prometheus.yml

# 4. Start Grafana
# Windows: Start-Service Grafana
# Linux: systemctl start grafana-server

# 5. Access Grafana
http://localhost:3002

# 6. Import dashboards
# Grafana → Dashboards → Import → Upload JSON from grafana_provisioning/dashboards/
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **MetricsRegistry** | Singleton holding all Prometheus metrics |
| **Metric Groups** | Organize related metrics for selective enable/disable |
| **Cardinality** | Unique label combinations (keep low!) |
| **Recording Rules** | Pre-compute expensive queries |
| **Alert Rules** | Define SLA breach conditions |
| **Grafana Dashboards** | Visualize metrics over time |

### VS Code Tasks

```bash
# Start metrics server (9108)
Task: "Metrics: Start 9108"

# Start observability stack (Prometheus + Grafana)
Task: "Observability: Start baseline"

# Generate Grafana dashboards
Task: "Grafana: Generate dashboards"

# Check metric catalog
Task: "Docs: Generate metrics catalog"
```

### Related Guides

- **[Collector System Guide](COLLECTOR_SYSTEM_GUIDE.md)**: Collector metrics integration
- **[Analytics Guide](ANALYTICS_GUIDE.md)**: Analytics metrics (IV, Greeks, PCR)
- **[Storage Guide](STORAGE_GUIDE.md)**: Storage performance metrics
- **[Configuration Guide](CONFIGURATION_GUIDE.md)**: Metrics configuration

### Further Reading

- **Prometheus Documentation**: https://prometheus.io/docs/
- **Grafana Documentation**: https://grafana.com/docs/
- **PromQL Tutorial**: https://prometheus.io/docs/prometheus/latest/querying/basics/
- **METRICS_CATALOG.md**: Complete metric inventory
- **METRICS_GOVERNANCE.md**: Cardinality governance policies

---

**End of Metrics Guide**
