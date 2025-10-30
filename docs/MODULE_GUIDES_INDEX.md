# Module Guides Index

This directory contains comprehensive user guides for all major G6 platform modules.

## Available Guides

### 1. ✅ **Weekday Master System** - `WEEKDAY_MASTER_COMPLETE_GUIDE.md`
Complete guide for weekday master file generation with three complementary systems:
- Batch Generator (historical data processing)
- Real-time Builder (live market hours updates)
- EOD Updater (automated daily execution)

**Coverage:** 
- System architecture and workflows
- VS Code tasks integration
- Task Scheduler automation
- Quality reporting and monitoring
- Troubleshooting and best practices

---

### 2. ✅ **Data Collection System** - `COLLECTOR_SYSTEM_GUIDE.md`
Complete guide for market data collection pipeline:
- Providers (Kite Live, Mock, Synthetic)
- Collectors (unified collection orchestration)
- Orchestrator (lifecycle and timing management)

**Coverage:**
- Provider selection and configuration
- Collection cycle flow
- Pipeline architecture
- Market hours gating
- Error handling and resilience
- Monitoring and troubleshooting

---

### 3. ✅ **Analytics & Greeks** - `ANALYTICS_GUIDE.md`
Complete guide for options analytics and calculations:
- Implied Volatility (Newton-Raphson solver)
- Option Greeks (Delta, Gamma, Vega, Theta, Rho)
- Black-Scholes pricing
- Put-Call Ratio (PCR)
- Market breadth indicators
- Volatility surface construction

**Coverage:**
- OptionGreeks class API
- IV solver algorithm and convergence
- Complete workflow examples
- Configuration and monitoring
- Best practices

---

### 4. ✅ **Storage & Persistence** - `STORAGE_GUIDE.md`
Complete guide for data storage systems:
- CSV Sink (file-based persistence)
- InfluxDB Sink (time-series database)
- Data Access Layer
- Retention policies
- Backfill procedures

**Coverage:**
- CsvSink and InfluxSink classes
- Batch buffering and circuit breakers
- Directory structure and file formats
- Flux queries and data access
- Retention and archival

---

### 5. ✅ **Metrics & Observability** - `METRICS_GUIDE.md`
Complete guide for monitoring and observability:
- Prometheus metrics registry
- Metric groups and gating
- Cardinality management
- Grafana dashboards
- Alert rules
- Performance monitoring

**Coverage:**
- 145+ metrics catalog
- Group-based gating
- Cardinality controls
- Recording and alert rules
- Dashboard generation
- Troubleshooting

---

### 6. ✅ **Panels & Summary System** - `PANELS_GUIDE.md`
Complete guide for real-time dashboard and panels:
- Summary application (Rich/Plain modes)
- Panels writer and JSON artifacts
- Panel integrity verification
- Status manifests
- SSE streaming

**Coverage:**
- Panel factory and builders
- Summary rendering modes
- Integrity monitoring
- Complete workflows
- Best practices

---

### 7. ✅ **Configuration Management** - `CONFIGURATION_GUIDE.md`
Complete guide for configuration and environment:
- JSON configuration files
- Environment variables
- Feature toggles
- Config governance
- Schema validation

**Coverage:**
- ConfigLoader class
- Environment variable precedence
- Feature toggle patterns
- Complete workflows
- Best practices

---

### 8. ✅ **Authentication & Tokens** - `AUTH_GUIDE.md`
Complete guide for authentication and token management:
- Kite Connect authentication
- Token acquisition (headless & interactive)
- Token refresh and validation
- Secret management

**Coverage:**
- OAuth 2.0 flow
- Token manager CLI
- Token storage formats
- Auto-refresh logic
- Troubleshooting

---

### 9. ✅ **Testing & Quality** - `TESTING_GUIDE.md`
Complete guide for testing infrastructure:
- pytest configuration
- Two-phase testing (parallel + serial)
- Benchmarking
- Coverage requirements
- CI/CD integration

---

## Quick Reference

### By Use Case

**Getting Started:**
1. Read `COLLECTOR_SYSTEM_GUIDE.md` - Understand data collection
2. Read `WEEKDAY_MASTER_COMPLETE_GUIDE.md` - Setup aggregations
3. Read `CONFIGURATION_GUIDE.md` - Configure your environment

**Analytics & Calculations:**
1. `ANALYTICS_GUIDE.md` - Greeks, IV, PCR calculations
2. `STORAGE_GUIDE.md` - Where data is stored
3. `METRICS_GUIDE.md` - Monitor calculations

**Monitoring & Operations:**
1. `METRICS_GUIDE.md` - Setup Prometheus monitoring
2. `PANELS_GUIDE.md` - Real-time dashboards
3. `TESTING_GUIDE.md` - Quality assurance

**Advanced Topics:**
1. `AUTH_GUIDE.md` - Production authentication
2. `STORAGE_GUIDE.md` - InfluxDB and advanced storage
3. `CONFIGURATION_GUIDE.md` - Feature toggles and tuning

---

## Guide Status

| Guide | Status | Lines | Last Updated |
|-------|--------|-------|--------------|
| Weekday Master System | ✅ Complete | 1000+ | 2025-10-25 |
| Data Collection System | ✅ Complete | 1300+ | 2025-10-25 |
| Analytics & Greeks | 📝 Planned | - | - |
| Storage & Persistence | 📝 Planned | - | - |
| Metrics & Observability | 📝 Planned | - | - |
| Panels & Summary | 📝 Planned | - | - |
| Configuration | 📝 Planned | - | - |
| Token Management | 📝 Planned | - | - |
| Testing & Quality | 📝 Planned | - | - |

---

## Contributing Guidelines

When creating new module guides, follow this structure:

### 1. Overview Section
- What the module does
- Architecture diagram
- When to use it

### 2. Core Components
- Key files and their purposes
- Main classes and functions
- Configuration options

### 3. Usage Examples
- Quick start example
- Common patterns
- Advanced usage

### 4. Configuration Reference
- All environment variables
- Config file options
- Default values

### 5. Monitoring & Troubleshooting
- Common issues and solutions
- Health checks
- Debug mode

### 6. Best Practices
- DO's and DON'Ts
- Performance tips
- Security considerations

### 7. Integration
- How it connects to other modules
- VS Code tasks
- Command-line usage

---

## Cross-Module Dependencies

```
┌────────────────────────────────────────────────────┐
│                                                     │
│  Configuration ──────┬───────────────────────┐    │
│                      │                        │    │
│                      ▼                        ▼    │
│  Token Mgmt ──▶ Collectors ──▶ Analytics          │
│                      │            │                │
│                      ▼            │                │
│                   Storage ◀───────┘                │
│                      │                              │
│                      ▼                              │
│              Weekday Masters                        │
│                      │                              │
│                      │                              │
│         ┌────────────┴──────────┐                  │
│         ▼                        ▼                  │
│      Metrics                 Panels                 │
│         │                        │                  │
│         └────────────┬───────────┘                  │
│                      ▼                              │
│                 Observability                       │
│                                                     │
└────────────────────────────────────────────────────┘
```

---

## Documentation Standards

All module guides should:
- ✅ Include working code examples
- ✅ Show real command-line usage
- ✅ Provide configuration tables
- ✅ Include troubleshooting sections
- ✅ Cross-reference related modules
- ✅ Use consistent formatting
- ✅ Include VS Code task references

---

## Quick Start by Role

### **Data Analyst**
Start with:
1. `WEEKDAY_MASTER_COMPLETE_GUIDE.md` - Understand aggregated data
2. `STORAGE_GUIDE.md` - Access historical data
3. `PANELS_GUIDE.md` - Create dashboards

### **Developer**
Start with:
1. `COLLECTOR_SYSTEM_GUIDE.md` - Understand pipeline
2. `ANALYTICS_GUIDE.md` - Calculations and algorithms
3. `TESTING_GUIDE.md` - Write tests

### **DevOps / Operations**
Start with:
1. `CONFIGURATION_GUIDE.md` - Setup and deploy
2. `METRICS_GUIDE.md` - Monitor systems
3. `AUTH_GUIDE.md` - Manage credentials

### **Trader / User**
Start with:
1. `PANELS_GUIDE.md` - View live data
2. `WEEKDAY_MASTER_COMPLETE_GUIDE.md` - Access historical patterns
3. `ANALYTICS_GUIDE.md` - Understand metrics

---

## Finding Specific Information

### Environment Variables
- Collector settings: `COLLECTOR_SYSTEM_GUIDE.md` → Part 5
- Config variables: `CONFIGURATION_GUIDE.md`
- Complete catalog: `docs/ENV_VARS_CATALOG.md`
- Tuning quick reference: `docs/ENV_REFERENCE.md`

### Code Examples
- Collection pipeline: `COLLECTOR_SYSTEM_GUIDE.md` → Part 4
- Analytics usage: `ANALYTICS_GUIDE.md` → Examples
- Testing patterns: `TESTING_GUIDE.md`

### Troubleshooting
- Each guide has dedicated troubleshooting section
- Common issues: Check "Part 6" or "Monitoring" section
- Debug mode: Look for "Debug Mode" subsections

### VS Code Tasks
- Collection tasks: `COLLECTOR_SYSTEM_GUIDE.md` → Part 8
- Weekday tasks: `WEEKDAY_MASTER_COMPLETE_GUIDE.md` → Appendix A
- All tasks: `.vscode/tasks.json`

---

## Related Documentation

### Architecture & Design
- `docs/ARCHITECTURE.md` - System architecture
- `docs/PIPELINE_DESIGN.md` - Collection pipeline design
- `docs/UNIFIED_MODEL.md` - Data models

### Configuration & Environment
- `docs/ENVIRONMENT.md` - Environment setup
- `docs/CONFIG_KEYS_CATALOG.md` - Config reference
- `docs/ENV_VARS_CATALOG.md` - Environment variables

### Metrics & Monitoring
- `docs/METRICS_CATALOG.md` - All metrics
- `docs/OBSERVABILITY_DASHBOARDS.md` - Grafana dashboards
- `docs/RULES_CATALOG.md` - Alert rules

### Operations
- `docs/OPERATOR_MANUAL.md` - Operations guide
- `docs/DEPLOYMENT_GUIDE.md` - Deployment procedures
- `docs/RETENTION_POLICY.md` - Data retention

---

## Support

For questions or issues:
1. Check the relevant module guide first
2. Review troubleshooting sections
3. Check `README.md` for quick reference
4. Review existing documentation in `docs/`

---

## Changelog

### 2025-10-25
- ✅ Created `WEEKDAY_MASTER_COMPLETE_GUIDE.md` (1000+ lines)
- ✅ Created `COLLECTOR_SYSTEM_GUIDE.md` (1300+ lines)
- 📝 Planned remaining 7 module guides

### Next Steps
- Create `ANALYTICS_GUIDE.md`
- Create `STORAGE_GUIDE.md`
- Create `METRICS_GUIDE.md`
- Create `PANELS_GUIDE.md`
- Create `CONFIGURATION_GUIDE.md`
- Create `AUTH_GUIDE.md`
- Create `TESTING_GUIDE.md`

---

*This index is automatically maintained as new module guides are added.*
