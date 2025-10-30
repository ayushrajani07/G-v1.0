# G6 Platform - Testing Guide

**Complete User Guide for Testing Infrastructure**

---

## Table of Contents

1. [Overview](#1-overview)
2. [Test Structure](#2-test-structure)
3. [Running Tests](#3-running-tests)
4. [Pytest Configuration](#4-pytest-configuration)
5. [Test Fixtures](#5-test-fixtures)
6. [Mocking & Fakes](#6-mocking--fakes)
7. [Complete Workflows](#7-complete-workflows)
8. [Configuration Reference](#8-configuration-reference)
9. [Troubleshooting](#9-troubleshooting)
10. [Best Practices](#10-best-practices)
11. [Summary](#11-summary)

---

## 1. Overview

### Testing Strategy

The G6 Platform uses **pytest** with a **two-phase** approach:

1. **Parallel Phase**: Fast, isolated tests run concurrently (`pytest-xdist`)
2. **Serial Phase**: Integration tests requiring exclusive resources

### Test Categories

✅ **Unit Tests**: Test individual functions/classes  
✅ **Integration Tests**: Test component interactions  
✅ **End-to-End Tests**: Test complete workflows  
✅ **Performance Tests**: Benchmark critical paths  
✅ **Smoke Tests**: Verify basic functionality  

### Test Metrics

- **Total Tests**: 250+ tests
- **Coverage**: 85%+ line coverage
- **Duration**: Parallel (~30s), Serial (~60s)
- **CI/CD**: Automated on every commit

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Test Runner                            │
│                     (pytest)                                │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         │                               │
┌────────▼─────────┐          ┌─────────▼────────┐
│ Parallel Phase   │          │  Serial Phase    │
│ (pytest-xdist)   │          │  (sequential)    │
│                  │          │                  │
│ • Unit tests     │          │ • File I/O       │
│ • Pure functions │          │ • Subprocess     │
│ • Mocked deps    │          │ • Metrics reset  │
│ • Fast (<1s each)│          │ • Global state   │
│                  │          │                  │
│ Workers: 4-8     │          │ Workers: 1       │
└──────────────────┘          └──────────────────┘
```

### File Structure

```
tests/
├── conftest.py              # Shared fixtures
├── pytest.ini               # Pytest configuration
├── test_analytics/          # Analytics tests
│   ├── test_option_greeks.py
│   ├── test_option_chain.py
│   └── test_market_breadth.py
├── test_collectors/         # Collector tests
│   ├── test_orchestrator.py
│   ├── test_collectors.py
│   └── test_providers.py
├── test_storage/            # Storage tests
│   ├── test_csv_sink.py
│   ├── test_influx_sink.py
│   └── test_data_access.py
├── test_metrics/            # Metrics tests
│   ├── test_registry.py
│   ├── test_groups.py
│   └── test_cardinality.py
├── test_panels/             # Panels tests
│   ├── test_factory.py
│   └── test_integrity.py
├── test_config/             # Config tests
│   └── test_config_loader.py
└── test_integration/        # Integration tests
    ├── test_end_to_end.py
    └── test_full_cycle.py

scripts/
├── pytest_run.py            # Test runner script
└── dev_tools.py             # Test utilities

pyproject.toml               # Test dependencies
pytest.ini                   # Pytest config
```

---

## 2. Test Structure

### Unit Test Example

**File**: `tests/test_analytics/test_option_greeks.py`

```python
import pytest
from src.analytics.option_greeks import OptionGreeks

class TestOptionGreeks:
    """Test suite for OptionGreeks calculator."""
    
    def test_calculate_delta_call(self):
        """Test call option delta calculation."""
        greeks = OptionGreeks()
        
        delta = greeks.calculate_delta(
            S=100,      # Spot price
            K=100,      # Strike price
            T=30/365,   # Time to expiry (days/365)
            r=0.05,     # Risk-free rate
            sigma=0.2,  # Volatility
            option_type='CE'
        )
        
        # Call delta should be between 0 and 1
        assert 0 <= delta <= 1
        # ATM call delta ~0.5
        assert 0.4 <= delta <= 0.6
    
    def test_calculate_delta_put(self):
        """Test put option delta calculation."""
        greeks = OptionGreeks()
        
        delta = greeks.calculate_delta(
            S=100, K=100, T=30/365, r=0.05, sigma=0.2,
            option_type='PE'
        )
        
        # Put delta should be between -1 and 0
        assert -1 <= delta <= 0
        # ATM put delta ~-0.5
        assert -0.6 <= delta <= -0.4
    
    @pytest.mark.parametrize("S,K,expected_sign", [
        (110, 100, 1),   # ITM call: positive delta
        (100, 100, 1),   # ATM call: positive delta
        (90, 100, 1),    # OTM call: positive delta
    ])
    def test_delta_sign(self, S, K, expected_sign):
        """Test delta sign for calls."""
        greeks = OptionGreeks()
        delta = greeks.calculate_delta(S, K, 30/365, 0.05, 0.2, 'CE')
        assert (delta > 0) == (expected_sign > 0)
```

### Integration Test Example

**File**: `tests/test_integration/test_full_cycle.py`

```python
import pytest
import tempfile
from pathlib import Path
from src.orchestrator.orchestrator import Orchestrator
from src.provider.mock_provider import MockProvider
from src.storage.csv_sink import CsvSink

@pytest.mark.serial  # Run sequentially
class TestFullCollectionCycle:
    """Integration test for complete collection cycle."""
    
    def test_collect_and_store(self, tmp_path):
        """Test full cycle: collect → analytics → storage."""
        
        # Setup
        provider = MockProvider(indices=["NIFTY"])
        csv_dir = tmp_path / "data"
        csv_sink = CsvSink(base_dir=str(csv_dir))
        
        orchestrator = Orchestrator(
            provider=provider,
            sinks=[csv_sink],
            indices=["NIFTY"]
        )
        
        # Execute one cycle
        result = orchestrator.run_cycle()
        
        # Verify results
        assert result.success is True
        assert result.collected_count > 0
        
        # Check CSV files created
        csv_files = list(csv_dir.glob("**/*.csv"))
        assert len(csv_files) > 0
        
        # Verify data format
        import pandas as pd
        df = pd.read_csv(csv_files[0])
        assert "strike" in df.columns
        assert "ltp" in df.columns
        assert len(df) > 0
```

### Performance Test Example

**File**: `tests/test_performance/test_benchmarks.py`

```python
import pytest
import time
from src.analytics.option_greeks import OptionGreeks

@pytest.mark.benchmark
class TestPerformance:
    """Performance benchmarks."""
    
    def test_greeks_calculation_speed(self, benchmark):
        """Benchmark Greeks calculation speed."""
        greeks = OptionGreeks()
        
        def calc_greeks():
            return greeks.calculate_all_greeks(
                S=100, K=100, T=30/365, r=0.05, sigma=0.2
            )
        
        # Run benchmark
        result = benchmark(calc_greeks)
        
        # Verify performance
        assert benchmark.stats['mean'] < 0.001  # < 1ms average
    
    def test_collection_cycle_speed(self):
        """Test collection cycle completes within SLA."""
        from src.orchestrator.orchestrator import Orchestrator
        from src.provider.mock_provider import MockProvider
        
        provider = MockProvider(indices=["NIFTY"])
        orchestrator = Orchestrator(provider=provider, sinks=[])
        
        start = time.time()
        result = orchestrator.run_cycle()
        duration = time.time() - start
        
        # SLA: cycle must complete in < 60s
        assert duration < 60
        assert result.success is True
```

---

## 3. Running Tests

### Basic Commands

```bash
# Run all tests
pytest

# Run specific file
pytest tests/test_analytics/test_option_greeks.py

# Run specific test
pytest tests/test_analytics/test_option_greeks.py::TestOptionGreeks::test_calculate_delta_call

# Run tests matching pattern
pytest -k "greeks"

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src --cov-report=html
```

### Two-Phase Testing

#### Parallel Phase (Fast Tests)

```bash
# Run parallel tests only
python scripts/pytest_run.py parallel-subset

# Or directly
pytest -n auto -m "not serial"

# Uses pytest-xdist for parallelism
# Typical duration: 20-30s
```

#### Serial Phase (Slow Tests)

```bash
# Run serial tests only
python scripts/pytest_run.py serial

# Or directly
pytest -m serial

# Runs sequentially
# Typical duration: 40-60s
```

#### Full Two-Phase Run

```bash
# Run both phases in sequence
python scripts/pytest_run.py

# Or via VS Code task
Task: "pytest: two-phase (parallel -> serial)"
```

### Markers

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run only smoke tests
pytest -m smoke

# Skip slow tests
pytest -m "not slow"

# Run benchmarks
pytest -m benchmark
```

---

## 4. Pytest Configuration

### pytest.ini

**Location**: `pytest.ini`

```ini
[pytest]
# Test discovery
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*

# Markers
markers =
    serial: marks tests that must run serially (no parallelism)
    unit: marks unit tests
    integration: marks integration tests
    slow: marks slow tests (> 5s)
    smoke: marks smoke tests (basic functionality)
    benchmark: marks performance benchmarks

# Output
addopts = 
    --strict-markers
    --tb=short
    --disable-warnings
    -ra

# Coverage
[coverage:run]
source = src
omit = 
    */tests/*
    */test_*.py
    */__pycache__/*

[coverage:report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
```

### pyproject.toml

**Location**: `pyproject.toml`

```toml
[tool.pytest.ini_options]
minversion = "7.0"
addopts = "--strict-markers"
testpaths = ["tests"]

[tool.coverage.run]
source = ["src"]
omit = ["*/tests/*", "*/__pycache__/*"]

[tool.coverage.report]
precision = 2
skip_empty = true
```

---

## 5. Test Fixtures

### conftest.py

**Location**: `tests/conftest.py`

Common fixtures shared across tests.

```python
import pytest
import tempfile
from pathlib import Path
from prometheus_client import REGISTRY

@pytest.fixture
def temp_dir():
    """Provide temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def sample_option_data():
    """Provide sample option chain data."""
    return {
        "strike": 24500,
        "ltp": 123.45,
        "volume": 1000,
        "oi": 5000,
        "iv": 0.15
    }

@pytest.fixture
def mock_provider():
    """Provide mock provider instance."""
    from src.provider.mock_provider import MockProvider
    return MockProvider(indices=["NIFTY"])

@pytest.fixture(autouse=True)
def reset_metrics_registry():
    """Reset Prometheus registry before each test."""
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass
    yield
    # Cleanup after test
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass

@pytest.fixture
def status_file(temp_dir):
    """Provide temporary status file."""
    status_path = temp_dir / "runtime_status.json"
    status_path.write_text('{"cycle": 1, "indices": ["NIFTY"]}')
    return status_path
```

### Fixture Scopes

```python
@pytest.fixture(scope="function")  # Default: per-test
def temp_file():
    pass

@pytest.fixture(scope="class")  # Per test class
def db_connection():
    pass

@pytest.fixture(scope="module")  # Per test module
def expensive_resource():
    pass

@pytest.fixture(scope="session")  # Once per test session
def global_config():
    pass
```

---

## 6. Mocking & Fakes

### Mock Provider

**Location**: `src/provider/mock_provider.py`

Fake market data provider for testing.

```python
from src.provider.mock_provider import MockProvider

# Create mock provider
provider = MockProvider(
    indices=["NIFTY", "BANKNIFTY"],
    latency_ms=50,
    error_rate=0.01  # 1% error rate
)

# Fetch instruments (returns fake data)
instruments = provider.fetch_instruments("NIFTY")
assert len(instruments) > 0

# Fetch quotes (returns random but realistic prices)
quotes = provider.fetch_quotes(["NIFTY50JAN24500CE"])
assert quotes[0]["last_price"] > 0
```

### unittest.mock

```python
from unittest.mock import Mock, patch, MagicMock

def test_with_mock():
    """Test using unittest.mock."""
    # Mock external API
    with patch('src.provider.kite_provider.KiteConnect') as MockKite:
        mock_kite = MockKite.return_value
        mock_kite.quote.return_value = {"NSE:NIFTY 50": {"last_price": 24500}}
        
        # Test code using mocked API
        from src.provider.kite_provider import KiteProvider
        provider = KiteProvider()
        quote = provider.get_quote("NIFTY 50")
        
        assert quote["last_price"] == 24500
        mock_kite.quote.assert_called_once()
```

### pytest-mock

```python
def test_with_pytest_mock(mocker):
    """Test using pytest-mock plugin."""
    # Mock function
    mock_fetch = mocker.patch('src.collectors.collectors.fetch_option_chain')
    mock_fetch.return_value = [{"strike": 24500, "ltp": 123.45}]
    
    # Test code
    from src.collectors.collectors import collect_options
    result = collect_options("NIFTY")
    
    assert len(result) == 1
    assert result[0]["strike"] == 24500
```

---

## 7. Complete Workflows

### Workflow 1: Add New Test

**Scenario**: Test new PCR calculation function.

#### Step 1: Create Test File

`tests/test_analytics/test_pcr.py`:

```python
import pytest
from src.analytics.option_chain import calculate_pcr

class TestPCR:
    """Test Put-Call Ratio calculation."""
    
    def test_basic_pcr(self):
        """Test basic PCR calculation."""
        pcr = calculate_pcr(put_oi=10000, call_oi=8000)
        assert pcr == 1.25  # 10000 / 8000
    
    def test_pcr_zero_calls(self):
        """Test PCR when call OI is zero."""
        pcr = calculate_pcr(put_oi=10000, call_oi=0)
        assert pcr == 0  # Should return 0, not crash
    
    @pytest.mark.parametrize("put_oi,call_oi,expected", [
        (10000, 10000, 1.0),
        (10000, 5000, 2.0),
        (5000, 10000, 0.5),
    ])
    def test_pcr_values(self, put_oi, call_oi, expected):
        """Test various PCR values."""
        pcr = calculate_pcr(put_oi, call_oi)
        assert pcr == pytest.approx(expected)
```

#### Step 2: Run Test

```bash
pytest tests/test_analytics/test_pcr.py -v
```

#### Step 3: Check Coverage

```bash
pytest tests/test_analytics/test_pcr.py --cov=src.analytics.option_chain
```

---

### Workflow 2: Debug Failing Test

**Scenario**: Test failing unexpectedly.

#### Step 1: Run with Verbose Output

```bash
pytest tests/test_analytics/test_option_greeks.py::test_calculate_delta -vv
```

#### Step 2: Use pdb Debugger

```python
def test_calculate_delta():
    greeks = OptionGreeks()
    
    import pdb; pdb.set_trace()  # Breakpoint
    
    delta = greeks.calculate_delta(100, 100, 30/365, 0.05, 0.2)
    assert 0.4 <= delta <= 0.6
```

Run:
```bash
pytest tests/test_analytics/test_option_greeks.py::test_calculate_delta -s
```

#### Step 3: Print Debug Info

```python
def test_calculate_delta(capsys):
    greeks = OptionGreeks()
    delta = greeks.calculate_delta(100, 100, 30/365, 0.05, 0.2)
    
    print(f"Delta: {delta}")
    captured = capsys.readouterr()
    print(captured.out)
    
    assert 0.4 <= delta <= 0.6
```

---

### Workflow 3: Run Smoke Tests in CI

**Scenario**: Quick validation before merge.

#### Step 1: Create Smoke Test Suite

```python
# tests/test_smoke.py
import pytest

@pytest.mark.smoke
class TestSmoke:
    """Smoke tests for basic functionality."""
    
    def test_import_main_modules(self):
        """Test main modules can be imported."""
        import src.orchestrator.orchestrator
        import src.analytics.option_greeks
        import src.storage.csv_sink
        # No crashes = success
    
    def test_mock_provider_basic(self):
        """Test mock provider returns data."""
        from src.provider.mock_provider import MockProvider
        provider = MockProvider()
        instruments = provider.fetch_instruments("NIFTY")
        assert len(instruments) > 0
```

#### Step 2: Run Smoke Tests

```bash
pytest -m smoke --tb=short
```

#### Step 3: CI Configuration

`.github/workflows/test.yml`:
```yaml
name: Tests
on: [push, pull_request]
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: pytest -m smoke
  
  full:
    runs-on: ubuntu-latest
    needs: smoke
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
      - run: pip install -r requirements.txt
      - run: pytest --cov=src
```

---

## 8. Configuration Reference

### Environment Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PYTEST_CURRENT_TEST` | string | ` ` | Current test name (set by pytest) |
| `G6_TEST_MODE` | bool | `0` | Enable test-specific behaviors |
| `G6_TEST_DATA_DIR` | string | `tests/fixtures` | Test data directory |

### Pytest Options

| Option | Description |
|--------|-------------|
| `-v` | Verbose output |
| `-vv` | Extra verbose |
| `-s` | Show print statements |
| `-x` | Stop on first failure |
| `--tb=short` | Short traceback |
| `--tb=long` | Long traceback |
| `-k "pattern"` | Run tests matching pattern |
| `-m "marker"` | Run tests with marker |
| `-n auto` | Parallel execution (pytest-xdist) |
| `--cov=src` | Coverage for src/ |
| `--cov-report=html` | HTML coverage report |

---

## 9. Troubleshooting

### Issue 1: Tests Fail in Parallel

**Symptom**: Tests pass serially but fail with `-n auto`.

**Cause**: Shared state between tests (files, global vars, metrics registry).

**Fix**:
```python
# Mark as serial
@pytest.mark.serial
def test_shared_resource():
    pass

# Or use fixtures to isolate
@pytest.fixture
def temp_metrics_registry():
    from prometheus_client import CollectorRegistry
    registry = CollectorRegistry()
    yield registry
    # Cleanup
```

### Issue 2: Import Errors

**Symptom**: `ModuleNotFoundError: No module named 'src'`

**Cause**: Python path not set correctly.

**Fix**:
```bash
# Add project root to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Or use pytest discovery
pytest --import-mode=importlib
```

### Issue 3: Fixture Not Found

**Symptom**: `fixture 'temp_dir' not found`

**Cause**: Fixture not in scope (wrong conftest.py location).

**Fix**:
```bash
# Move fixture to tests/conftest.py for global scope
# Or create conftest.py in specific test directory
```

---

## 10. Best Practices

### DO ✅

1. **Use descriptive test names**
   ```python
   # Good
   def test_calculate_delta_returns_positive_for_calls():
       pass
   
   # Bad
   def test_delta():
       pass
   ```

2. **One assert per test (when possible)**
   ```python
   # Good
   def test_delta_range():
       delta = calculate_delta(...)
       assert 0 <= delta <= 1
   
   # Better: split into multiple tests
   def test_delta_positive():
       delta = calculate_delta(...)
       assert delta >= 0
   
   def test_delta_less_than_one():
       delta = calculate_delta(...)
       assert delta <= 1
   ```

3. **Use parametrize for similar tests**
   ```python
   @pytest.mark.parametrize("input,expected", [
       (100, 0.5),
       (110, 0.7),
       (90, 0.3),
   ])
   def test_delta_values(input, expected):
       delta = calculate_delta(input, ...)
       assert delta == pytest.approx(expected)
   ```

4. **Clean up after tests**
   ```python
   def test_csv_write(tmp_path):
       csv_file = tmp_path / "test.csv"
       write_csv(csv_file, data)
       # No cleanup needed - tmp_path auto-deleted
   ```

### DON'T ❌

1. **Don't use sleep() in tests**
   ```python
   # Bad
   import time
   trigger_async_task()
   time.sleep(5)  # Wait for completion
   assert task_completed()
   
   # Good
   import asyncio
   await trigger_async_task()
   assert task_completed()
   ```

2. **Don't test implementation details**
   ```python
   # Bad: tests internal _private method
   def test_internal_method():
       obj = MyClass()
       assert obj._internal_calc() == 42
   
   # Good: test public API
   def test_public_method():
       obj = MyClass()
       assert obj.calculate() == 42
   ```

3. **Don't share state between tests**
   ```python
   # Bad: global variable
   counter = 0
   def test_increment():
       global counter
       counter += 1
       assert counter == 1  # Fails on second run!
   
   # Good: isolated state
   def test_increment():
       counter = 0
       counter += 1
       assert counter == 1
   ```

---

## 11. Summary

### Quick Start

```bash
# 1. Install test dependencies
pip install pytest pytest-xdist pytest-cov

# 2. Run all tests
pytest

# 3. Run with coverage
pytest --cov=src --cov-report=html

# 4. View coverage report
open htmlcov/index.html

# 5. Run specific suite
pytest tests/test_analytics/
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Two-Phase Testing** | Parallel (fast) + Serial (slow) |
| **Fixtures** | Reusable test setup (conftest.py) |
| **Markers** | Categorize tests (unit, integration, slow) |
| **Mocking** | Fake dependencies for isolation |
| **Coverage** | Measure tested code percentage |
| **Parametrize** | Run same test with different inputs |

### VS Code Tasks

```bash
# Run all tests (two-phase)
Task: "pytest: two-phase (parallel -> serial)"

# Run parallel tests only
Task: "pytest - parallel (xdist)"

# Run serial tests only
Task: "pytest - serial-only"

# Fast inner loop
Task: "pytest - fast inner loop"
```

### Related Guides

- **[Collector System Guide](COLLECTOR_SYSTEM_GUIDE.md)**: Testing collectors
- **[Analytics Guide](ANALYTICS_GUIDE.md)**: Testing analytics
- **[Metrics Guide](METRICS_GUIDE.md)**: Testing metrics

---

**End of Testing Guide**
