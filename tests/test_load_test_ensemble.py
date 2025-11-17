"""
Unit tests for load test ensemble harness.

Tests argument parsing and mocked HTTP interactions.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


@pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
class TestAsyncLoadTester:
    """Tests for async load tester."""
    
    def test_import(self):
        """Test that we can import the module."""
        from scripts.ml import load_test_ensemble_async
        assert load_test_ensemble_async is not None
    
    def test_tester_initialization(self):
        """Test load tester initialization."""
        from scripts.ml.load_test_ensemble_async import AsyncLoadTester
        
        tester = AsyncLoadTester(
            api_host="localhost",
            api_port=9210,
            indices=["NIFTY"],
            qps=10.0,
            concurrency=5,
            duration=10,
        )
        
        assert tester.api_host == "localhost"
        assert tester.api_port == 9210
        assert tester.indices == ["NIFTY"]
        assert tester.qps == 10.0
        assert tester.concurrency == 5
        assert tester.duration == 10
        assert tester.warmup == 0
        assert tester.horizons == [30, 60, 120]
        assert tester.detail == "snapshot"
        assert tester.cache_bust is False
    
    def test_tester_custom_params(self):
        """Test load tester with custom parameters."""
        from scripts.ml.load_test_ensemble_async import AsyncLoadTester
        
        tester = AsyncLoadTester(
            api_host="api.example.com",
            api_port=8080,
            indices=["NIFTY", "BANKNIFTY"],
            qps=50.0,
            concurrency=20,
            duration=300,
            warmup=30,
            horizons=[60, 120],
            detail="full",
            cache_bust=True,
        )
        
        assert tester.api_host == "api.example.com"
        assert tester.api_port == 8080
        assert tester.indices == ["NIFTY", "BANKNIFTY"]
        assert tester.qps == 50.0
        assert tester.concurrency == 20
        assert tester.duration == 300
        assert tester.warmup == 30
        assert tester.horizons == [60, 120]
        assert tester.detail == "full"
        assert tester.cache_bust is True
    
    @pytest.mark.asyncio
    async def test_make_forecast_request_success(self):
        """Test successful forecast request."""
        from scripts.ml.load_test_ensemble_async import AsyncLoadTester
        
        tester = AsyncLoadTester(
            api_host="localhost",
            api_port=9210,
            indices=["NIFTY"],
            qps=10.0,
            concurrency=5,
            duration=10,
        )
        
        # Mock httpx client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "forecast": {"p10": 100, "p50": 110, "p90": 120},
            "confidence": 0.8,
        }
        mock_client.get.return_value = mock_response
        
        result = await tester.make_forecast_request(
            mock_client, "NIFTY", 60
        )
        
        assert result["status"] == "success"
        assert result["index"] == "NIFTY"
        assert result["horizon"] == 60
        assert result["has_p10"] is True
        assert result["has_p50"] is True
        assert result["has_p90"] is True
        assert "latency" in result
        assert result["latency"] >= 0
    
    @pytest.mark.asyncio
    async def test_make_forecast_request_http_error(self):
        """Test forecast request with HTTP error."""
        from scripts.ml.load_test_ensemble_async import AsyncLoadTester
        
        tester = AsyncLoadTester(
            api_host="localhost",
            api_port=9210,
            indices=["NIFTY"],
            qps=10.0,
            concurrency=5,
            duration=10,
        )
        
        # Mock httpx client with 404 error
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get.return_value = mock_response
        
        result = await tester.make_forecast_request(
            mock_client, "NIFTY", 60
        )
        
        assert result["status"] == "http_error"
        assert result["error_code"] == 404
        assert result["index"] == "NIFTY"
        assert result["horizon"] == 60
    
    @pytest.mark.asyncio
    async def test_make_forecast_request_timeout(self):
        """Test forecast request with timeout."""
        from scripts.ml.load_test_ensemble_async import AsyncLoadTester
        
        tester = AsyncLoadTester(
            api_host="localhost",
            api_port=9210,
            indices=["NIFTY"],
            qps=10.0,
            concurrency=5,
            duration=10,
        )
        
        # Mock httpx client with timeout
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("Timeout")
        
        result = await tester.make_forecast_request(
            mock_client, "NIFTY", 60
        )
        
        assert result["status"] == "timeout"
        assert result["index"] == "NIFTY"
        assert result["horizon"] == 60
    
    @pytest.mark.asyncio
    async def test_fetch_cache_metrics_success(self):
        """Test fetching cache metrics successfully."""
        from scripts.ml.load_test_ensemble_async import AsyncLoadTester
        
        tester = AsyncLoadTester(
            api_host="localhost",
            api_port=9210,
            indices=["NIFTY"],
            qps=10.0,
            concurrency=5,
            duration=10,
        )
        
        # Mock httpx client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "window_cache": {"enabled": True, "hit_ratio": 0.85},
            "disk_cache": {"enabled": True, "hits": 100},
        }
        mock_client.get.return_value = mock_response
        
        result = await tester.fetch_cache_metrics(mock_client)
        
        assert "window_cache" in result
        assert result["window_cache"]["enabled"] is True
        assert result["window_cache"]["hit_ratio"] == 0.85
    
    @pytest.mark.asyncio
    async def test_fetch_cache_metrics_error(self):
        """Test fetching cache metrics with error."""
        from scripts.ml.load_test_ensemble_async import AsyncLoadTester
        
        tester = AsyncLoadTester(
            api_host="localhost",
            api_port=9210,
            indices=["NIFTY"],
            qps=10.0,
            concurrency=5,
            duration=10,
        )
        
        # Mock httpx client with error
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection error")
        
        result = await tester.fetch_cache_metrics(mock_client)
        
        assert result == {}
    
    def test_analyze_results_empty(self):
        """Test analyze results with no data."""
        from scripts.ml.load_test_ensemble_async import AsyncLoadTester
        
        tester = AsyncLoadTester(
            api_host="localhost",
            api_port=9210,
            indices=["NIFTY"],
            qps=10.0,
            concurrency=5,
            duration=10,
        )
        
        result = tester.analyze_results()
        
        assert result["status"] == "error"
        assert result["message"] == "No results"
    
    def test_analyze_results_with_data(self):
        """Test analyze results with mock data."""
        from scripts.ml.load_test_ensemble_async import AsyncLoadTester
        
        tester = AsyncLoadTester(
            api_host="localhost",
            api_port=9210,
            indices=["NIFTY", "BANKNIFTY"],
            qps=10.0,
            concurrency=5,
            duration=10,
        )
        
        # Add mock results
        tester.test_results = [
            {"status": "success", "latency": 0.1, "index": "NIFTY", "horizon": 60},
            {"status": "success", "latency": 0.2, "index": "NIFTY", "horizon": 60},
            {"status": "success", "latency": 0.15, "index": "BANKNIFTY", "horizon": 60},
            {"status": "http_error", "error_code": 500, "index": "NIFTY", "horizon": 60},
        ]
        
        result = tester.analyze_results()
        
        assert "summary" in result
        assert result["summary"]["total_requests"] == 4
        assert result["summary"]["successful"] == 3
        assert result["summary"]["failed"] == 1
        assert "latency_ms" in result
        assert "per_index" in result
        assert "NIFTY" in result["per_index"]
        assert "BANKNIFTY" in result["per_index"]
    
    def test_save_csv(self, tmp_path):
        """Test saving results to CSV."""
        from scripts.ml.load_test_ensemble_async import AsyncLoadTester
        
        tester = AsyncLoadTester(
            api_host="localhost",
            api_port=9210,
            indices=["NIFTY"],
            qps=10.0,
            concurrency=5,
            duration=10,
        )
        
        # Add mock results
        tester.test_results = [
            {
                "status": "success",
                "latency": 0.1,
                "index": "NIFTY",
                "horizon": 60,
                "timestamp": "2025-11-17T12:00:00",
                "worker_id": 0,
            },
        ]
        
        csv_path = tmp_path / "test.csv"
        tester.save_csv(csv_path)
        
        assert csv_path.exists()
        content = csv_path.read_text()
        assert "timestamp,index,horizon,latency_ms" in content
        assert "NIFTY" in content


class TestArgumentParsing:
    """Tests for command-line argument parsing."""
    
    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    def test_parse_basic_args(self):
        """Test parsing basic command-line arguments."""
        from scripts.ml.load_test_ensemble_async import main
        
        test_args = [
            "load_test_ensemble_async.py",
            "--indices", "NIFTY",
            "--qps", "10",
            "--duration", "5",
        ]
        
        with patch("sys.argv", test_args):
            with patch("scripts.ml.load_test_ensemble_async.asyncio.run") as mock_run:
                # Mock asyncio.run to avoid actually running the test
                mock_run.return_value = {
                    "targets": {"overall_pass": True}
                }
                
                with pytest.raises(SystemExit) as exc_info:
                    main()
                
                # Should exit with 0 (success)
                assert exc_info.value.code == 0
    
    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    def test_parse_multiple_indices(self):
        """Test parsing multiple indices."""
        from scripts.ml.load_test_ensemble_async import main
        
        test_args = [
            "load_test_ensemble_async.py",
            "--indices", "NIFTY", "BANKNIFTY",
            "--qps", "10",
            "--duration", "5",
        ]
        
        with patch("sys.argv", test_args):
            with patch("scripts.ml.load_test_ensemble_async.asyncio.run") as mock_run:
                mock_run.return_value = {
                    "targets": {"overall_pass": True}
                }
                
                with pytest.raises(SystemExit) as exc_info:
                    main()
                
                assert exc_info.value.code == 0
    
    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    def test_parse_with_csv_output(self, tmp_path):
        """Test parsing with CSV output option."""
        from scripts.ml.load_test_ensemble_async import main
        
        csv_file = tmp_path / "output.csv"
        json_file = tmp_path / "output.json"
        
        test_args = [
            "load_test_ensemble_async.py",
            "--indices", "NIFTY",
            "--qps", "10",
            "--duration", "5",
            "--csv-out", str(csv_file),
            "--output", str(json_file),
        ]
        
        with patch("sys.argv", test_args):
            with patch("scripts.ml.load_test_ensemble_async.asyncio.run") as mock_run:
                mock_results = {
                    "targets": {"overall_pass": True},
                    "summary": {"total_requests": 10},
                }
                mock_run.return_value = mock_results
                
                # Mock the tester's save_csv method
                with patch("scripts.ml.load_test_ensemble_async.AsyncLoadTester.save_csv"):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    
                    assert exc_info.value.code == 0
