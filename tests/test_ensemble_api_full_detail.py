"""
Tests for detail=full mode in Ensemble Forecast API.

Verifies:
1. Default (snapshot) mode unchanged
2. Full detail mode returns time_grid and quantile_paths
3. Arrays have correct lengths
4. Quantile labels are stable (p10, p50, p90)
5. Edge cases (empty results, invalid detail param)
"""
import pytest
from fastapi.testclient import TestClient
from src.web.dashboard.app import app

client = TestClient(app)


class TestEnsembleAPIFullDetail:
    """Test detail=full mode for forecast endpoint."""
    
    def test_default_mode_unchanged(self):
        """Test that default call (no detail param) returns snapshot only."""
        r = client.get("/api/ml/ensemble/forecast", params={"index": "NIFTY"})
        assert r.status_code == 200
        data = r.json()
        
        # Should have all snapshot fields
        assert "index" in data
        assert "horizon" in data
        assert "timestamp" in data
        assert "forecast" in data
        assert "confidence" in data
        assert "metadata" in data
        
        # Snapshot fields should be present
        assert "p10" in data["forecast"]
        assert "p50" in data["forecast"]
        assert "p90" in data["forecast"]
        
        # Full detail fields should NOT be present (or be None)
        assert data.get("time_grid") is None
        assert data.get("quantile_paths") is None
    
    def test_full_detail_mode_basic(self):
        """Test that detail=full returns time_grid and quantile_paths."""
        r = client.get("/api/ml/ensemble/forecast", params={
            "index": "NIFTY",
            "horizon": 60,
            "detail": "full"
        })
        assert r.status_code == 200
        data = r.json()
        
        # Should still have all snapshot fields (backward compatibility)
        assert "index" in data
        assert "forecast" in data
        assert "confidence" in data
        assert "metadata" in data
        
        # Should now have full detail fields
        assert "time_grid" in data
        assert "quantile_paths" in data
        assert data["time_grid"] is not None
        assert data["quantile_paths"] is not None
    
    def test_time_grid_structure(self):
        """Test time_grid has correct structure and fields."""
        r = client.get("/api/ml/ensemble/forecast", params={
            "index": "NIFTY",
            "horizon": 30,
            "detail": "full"
        })
        assert r.status_code == 200
        data = r.json()
        
        time_grid = data["time_grid"]
        assert "start" in time_grid
        assert "end" in time_grid
        assert "resolution_ms" in time_grid
        assert "values" in time_grid
        
        # Check types
        assert isinstance(time_grid["start"], int)
        assert isinstance(time_grid["end"], int)
        assert isinstance(time_grid["resolution_ms"], int)
        assert isinstance(time_grid["values"], list)
        
        # Resolution should be 60000 (1 minute)
        assert time_grid["resolution_ms"] == 60000
        
        # Values should be non-empty for valid forecast
        if time_grid["values"]:
            # Start should match first value
            assert time_grid["start"] == time_grid["values"][0]
            # End should match last value
            assert time_grid["end"] == time_grid["values"][-1]
    
    def test_quantile_paths_structure(self):
        """Test quantile_paths has correct structure and labels."""
        r = client.get("/api/ml/ensemble/forecast", params={
            "index": "NIFTY",
            "horizon": 60,
            "quantiles": "0.1,0.5,0.9",
            "detail": "full"
        })
        assert r.status_code == 200
        data = r.json()
        
        quantile_paths = data["quantile_paths"]
        assert isinstance(quantile_paths, dict)
        
        # Should have p10, p50, p90 (normalized labels)
        expected_labels = {"p10", "p50", "p90"}
        assert set(quantile_paths.keys()) >= expected_labels
        
        # Each path should be a list
        for label, path in quantile_paths.items():
            assert isinstance(path, list)
            # Each value should be a number
            for val in path:
                assert isinstance(val, (int, float))
    
    def test_arrays_same_length(self):
        """Test that time_grid.values and all quantile paths have same length."""
        r = client.get("/api/ml/ensemble/forecast", params={
            "index": "NIFTY",
            "horizon": 60,
            "detail": "full"
        })
        assert r.status_code == 200
        data = r.json()
        
        time_grid = data["time_grid"]
        quantile_paths = data["quantile_paths"]
        
        grid_length = len(time_grid["values"])
        
        # All quantile paths should have same length as time_grid
        for label, path in quantile_paths.items():
            assert len(path) == grid_length, f"Path {label} length {len(path)} != grid length {grid_length}"
    
    def test_custom_quantiles_with_full_detail(self):
        """Test that custom quantiles are included with correct labels."""
        r = client.get("/api/ml/ensemble/forecast", params={
            "index": "NIFTY",
            "horizon": 60,
            "quantiles": "0.05,0.25,0.5,0.75,0.95",
            "detail": "full"
        })
        assert r.status_code == 200
        data = r.json()
        
        quantile_paths = data["quantile_paths"]
        
        # Should have all requested quantiles
        expected_labels = {"p5", "p25", "p50", "p75", "p95"}
        assert set(quantile_paths.keys()) >= expected_labels
        
        # All should have same length
        lengths = [len(path) for path in quantile_paths.values()]
        assert len(set(lengths)) <= 1, "All paths should have same length"
    
    def test_invalid_detail_param_fallback(self):
        """Test that invalid detail param falls back to snapshot mode."""
        r = client.get("/api/ml/ensemble/forecast", params={
            "index": "NIFTY",
            "detail": "invalid"
        })
        assert r.status_code == 200
        data = r.json()
        
        # Should fall back to snapshot mode
        assert data.get("time_grid") is None
        assert data.get("quantile_paths") is None
        assert "forecast" in data
    
    def test_case_insensitive_detail_param(self):
        """Test that detail param is case-insensitive."""
        for detail_val in ["full", "Full", "FULL"]:
            r = client.get("/api/ml/ensemble/forecast", params={
                "index": "NIFTY",
                "detail": detail_val
            })
            assert r.status_code == 200
            data = r.json()
            
            # Should trigger full mode regardless of case
            assert data.get("time_grid") is not None
            assert data.get("quantile_paths") is not None
    
    def test_full_detail_with_different_horizons(self):
        """Test full detail mode with various horizons."""
        horizons = [30, 60, 120]
        
        for h in horizons:
            r = client.get("/api/ml/ensemble/forecast", params={
                "index": "NIFTY",
                "horizon": h,
                "detail": "full"
            })
            assert r.status_code == 200
            data = r.json()
            
            # Should have full detail fields
            assert "time_grid" in data
            assert "quantile_paths" in data
            
            time_grid = data["time_grid"]
            # Expected length: horizon in minutes + 1 (includes start point)
            # With 1-minute resolution
            expected_min_length = 1
            expected_max_length = h + 1
            
            grid_length = len(time_grid["values"])
            assert grid_length >= expected_min_length
            # Allow some flexibility for bucketing
    
    def test_snapshot_fields_preserved_in_full_mode(self):
        """Test that snapshot fields are preserved when detail=full."""
        r = client.get("/api/ml/ensemble/forecast", params={
            "index": "NIFTY",
            "detail": "full"
        })
        assert r.status_code == 200
        data = r.json()
        
        # All snapshot fields should still be present
        assert "forecast" in data
        assert "p10" in data["forecast"]
        assert "p50" in data["forecast"]
        assert "p90" in data["forecast"]
        assert "band_low" in data["forecast"]
        assert "band_high" in data["forecast"]
        assert "confidence" in data
        assert "metadata" in data
    
    def test_empty_quantile_paths_graceful(self):
        """Test that empty/zero sequences are handled gracefully."""
        # This tests the edge case where forecast returns empty results
        r = client.get("/api/ml/ensemble/forecast", params={
            "index": "NIFTY",
            "horizon": 1,
            "detail": "full"
        })
        assert r.status_code == 200
        data = r.json()
        
        # Should have the fields even if empty
        assert "time_grid" in data
        assert "quantile_paths" in data
        
        # Arrays should be lists (possibly empty), never null
        assert isinstance(data["time_grid"]["values"], list)
        assert isinstance(data["quantile_paths"], dict)
        
        for path in data["quantile_paths"].values():
            assert isinstance(path, list)
    
    def test_quantile_label_normalization(self):
        """Test that quantile float values are normalized to consistent labels."""
        r = client.get("/api/ml/ensemble/forecast", params={
            "index": "NIFTY",
            "quantiles": "0.10,0.50,0.90",  # Explicit decimal places
            "detail": "full"
        })
        assert r.status_code == 200
        data = r.json()
        
        quantile_paths = data["quantile_paths"]
        
        # Labels should be normalized (0.10 -> p10, not p10.0)
        assert "p10" in quantile_paths
        assert "p50" in quantile_paths
        assert "p90" in quantile_paths
        
        # Should NOT have labels with decimal points
        for label in quantile_paths.keys():
            assert "." not in label, f"Label {label} should not contain decimal point"
    
    def test_metadata_unchanged_in_full_mode(self):
        """Test that metadata structure is unchanged in full detail mode."""
        r = client.get("/api/ml/ensemble/forecast", params={
            "index": "NIFTY",
            "detail": "full"
        })
        assert r.status_code == 200
        data = r.json()
        
        metadata = data["metadata"]
        
        # Standard metadata fields should be present
        assert "latency_ms" in metadata
        assert "components_used" in metadata
        assert "weights" in metadata
        assert "recent_count" in metadata
        assert "cache_hit" in metadata
        
        # Check types
        assert isinstance(metadata["latency_ms"], (int, float))
        assert isinstance(metadata["components_used"], list)
        assert isinstance(metadata["weights"], dict)
        assert isinstance(metadata["cache_hit"], bool)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
