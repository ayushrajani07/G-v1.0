"""Tests for scripts/ml/validate_metrics.py"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add scripts/ml to path so we can import the module
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "ml"))

import validate_metrics


SAMPLE_METRICS_TEXT = """
# HELP g6_forecast_latency_ms Forecast latency in milliseconds
# TYPE g6_forecast_latency_ms histogram
g6_forecast_latency_ms_bucket{le="10"} 5
g6_forecast_latency_ms_bucket{le="50"} 15
g6_forecast_latency_ms_bucket{le="100"} 25
g6_forecast_latency_ms_bucket{le="+Inf"} 30
g6_forecast_latency_ms_sum 1250.5
g6_forecast_latency_ms_count 30
# HELP g6_forecast_cache_hits_total Total cache hits
# TYPE g6_forecast_cache_hits_total counter
g6_forecast_cache_hits_total 100
# HELP g6_forecast_cache_misses_total Total cache misses
# TYPE g6_forecast_cache_misses_total counter
g6_forecast_cache_misses_total 25
"""


def test_parse_prometheus_metrics():
    """Test parsing of Prometheus text format."""
    metrics = validate_metrics.parse_prometheus_metrics(SAMPLE_METRICS_TEXT)
    
    # Check that metrics were parsed
    assert "g6_forecast_latency_ms_sum" in metrics
    assert "g6_forecast_latency_ms_count" in metrics
    assert "g6_forecast_cache_hits_total" in metrics
    assert "g6_forecast_cache_misses_total" in metrics
    
    # Check values
    assert metrics["g6_forecast_latency_ms_sum"][0]["value"] == 1250.5
    assert metrics["g6_forecast_latency_ms_count"][0]["value"] == 30
    assert metrics["g6_forecast_cache_hits_total"][0]["value"] == 100
    assert metrics["g6_forecast_cache_misses_total"][0]["value"] == 25


def test_extract_histogram_sample():
    """Test extraction of histogram sample data."""
    metrics = validate_metrics.parse_prometheus_metrics(SAMPLE_METRICS_TEXT)
    
    # Extract histogram for latency metric
    histogram = validate_metrics.extract_histogram_sample(metrics, "g6_forecast_latency_ms")
    
    assert histogram is not None
    assert histogram["sum"] == 1250.5
    assert histogram["count"] == 30


def test_extract_histogram_sample_missing():
    """Test extraction when histogram is not present."""
    metrics = {"some_other_metric": [{"value": 42}]}
    
    histogram = validate_metrics.extract_histogram_sample(metrics, "g6_forecast_latency_ms")
    
    assert histogram is None


@patch("validate_metrics.httpx.get")
def test_validate_metrics_success(mock_get):
    """Test successful validation with all metrics present."""
    # Mock the HTTP response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = SAMPLE_METRICS_TEXT
    mock_get.return_value = mock_response
    
    # Validate metrics
    result = validate_metrics.validate_metrics(
        "http://localhost:9500/metrics",
        ["g6_forecast_latency_ms", "g6_forecast_cache_hits_total"]
    )
    
    # Check result
    assert "timestamp" in result
    assert result["found"] == ["g6_forecast_latency_ms", "g6_forecast_cache_hits_total"]
    assert result["missing"] == []
    assert "latency_histogram_sample" in result
    assert result["latency_histogram_sample"]["count"] == 30
    assert result["latency_histogram_sample"]["sum"] == 1250.5


@patch("validate_metrics.httpx.get")
def test_validate_metrics_missing(mock_get):
    """Test validation with missing metrics."""
    # Mock the HTTP response with only one metric
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = """
g6_forecast_cache_hits_total 100
"""
    mock_get.return_value = mock_response
    
    # Validate metrics
    result = validate_metrics.validate_metrics(
        "http://localhost:9500/metrics",
        ["g6_forecast_latency_ms", "g6_forecast_cache_hits_total"]
    )
    
    # Check result
    assert result["found"] == ["g6_forecast_cache_hits_total"]
    assert result["missing"] == ["g6_forecast_latency_ms"]


@patch("validate_metrics.httpx.get")
def test_validate_metrics_http_error(mock_get):
    """Test validation with HTTP error."""
    # Mock the HTTP response with error
    mock_response = Mock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_get.return_value = mock_response
    
    # Validate metrics
    result = validate_metrics.validate_metrics(
        "http://localhost:9500/metrics",
        ["g6_forecast_latency_ms"]
    )
    
    # Check result
    assert result["found"] == []
    assert result["missing"] == ["g6_forecast_latency_ms"]
    assert "error" in result
    assert "404" in result["error"]


@patch("validate_metrics.httpx.get")
def test_validate_metrics_timeout(mock_get):
    """Test validation with timeout."""
    import httpx
    
    # Mock timeout exception
    mock_get.side_effect = httpx.TimeoutException("Connection timeout")
    
    # Validate metrics
    result = validate_metrics.validate_metrics(
        "http://localhost:9500/metrics",
        ["g6_forecast_latency_ms"]
    )
    
    # Check result
    assert result["found"] == []
    assert result["missing"] == ["g6_forecast_latency_ms"]
    assert "error" in result
    assert "Timeout" in result["error"]


@patch("validate_metrics.httpx.get")
def test_validate_metrics_connect_error(mock_get):
    """Test validation with connection error."""
    import httpx
    
    # Mock connection error
    mock_get.side_effect = httpx.ConnectError("Connection refused")
    
    # Validate metrics
    result = validate_metrics.validate_metrics(
        "http://localhost:9500/metrics",
        ["g6_forecast_latency_ms"]
    )
    
    # Check result
    assert result["found"] == []
    assert result["missing"] == ["g6_forecast_latency_ms"]
    assert "error" in result


def test_parse_metrics_with_labels():
    """Test parsing metrics with labels."""
    metrics_text = """
http_requests_total{method="GET",status="200"} 123
http_requests_total{method="POST",status="200"} 45
"""
    metrics = validate_metrics.parse_prometheus_metrics(metrics_text)
    
    assert "http_requests_total" in metrics
    assert len(metrics["http_requests_total"]) == 2
    assert metrics["http_requests_total"][0]["labels"]["method"] == "GET"
    assert metrics["http_requests_total"][0]["labels"]["status"] == "200"
    assert metrics["http_requests_total"][0]["value"] == 123


def test_parse_metrics_empty_lines_and_comments():
    """Test parsing handles empty lines and comments."""
    metrics_text = """
# This is a comment
# TYPE my_metric counter

my_metric 42

# Another comment
another_metric 100
"""
    metrics = validate_metrics.parse_prometheus_metrics(metrics_text)
    
    assert "my_metric" in metrics
    assert "another_metric" in metrics
    assert metrics["my_metric"][0]["value"] == 42
    assert metrics["another_metric"][0]["value"] == 100


@patch("validate_metrics.httpx.get")
def test_main_success(mock_get, tmp_path):
    """Test main function with successful validation."""
    # Mock the HTTP response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = SAMPLE_METRICS_TEXT
    mock_get.return_value = mock_response
    
    # Create output path
    output_file = tmp_path / "metrics_validation.json"
    
    # Test with sys.argv patching
    test_args = [
        "validate_metrics.py",
        "--url", "http://localhost:9500/metrics",
        "--required", "g6_forecast_latency_ms,g6_forecast_cache_hits_total",
        "--out", str(output_file)
    ]
    
    with patch("sys.argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            validate_metrics.main()
        
        # Should exit with 0 (success)
        assert exc_info.value.code == 0
    
    # Check output file was created
    assert output_file.exists()
    
    # Check output content
    with open(output_file) as f:
        result = json.load(f)
    
    assert result["found"] == ["g6_forecast_latency_ms", "g6_forecast_cache_hits_total"]
    assert result["missing"] == []


@patch("validate_metrics.httpx.get")
def test_main_failure(mock_get, tmp_path):
    """Test main function with missing metrics."""
    # Mock the HTTP response with missing metric
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "g6_forecast_cache_hits_total 100"
    mock_get.return_value = mock_response
    
    # Create output path
    output_file = tmp_path / "metrics_validation.json"
    
    # Test with sys.argv patching
    test_args = [
        "validate_metrics.py",
        "--url", "http://localhost:9500/metrics",
        "--required", "g6_forecast_latency_ms,g6_forecast_cache_hits_total",
        "--out", str(output_file)
    ]
    
    with patch("sys.argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            validate_metrics.main()
        
        # Should exit with 1 (failure)
        assert exc_info.value.code == 1
    
    # Check output file was created
    assert output_file.exists()
    
    # Check output content
    with open(output_file) as f:
        result = json.load(f)
    
    assert "g6_forecast_latency_ms" in result["missing"]
