"""Unit tests for Phase 9 ANN cache functionality."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.path_forecast.ann_cache import (
    get_ann_windows,
    put_ann_windows,
    load_ann_index_from_disk,
    save_ann_index_to_disk,
    get_ann_window_cache_stats,
    get_ann_disk_cache_stats,
    clear_ann_window_cache,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache and reset stats before each test."""
    from src.path_forecast.ann_cache import reset_cache_stats
    clear_ann_window_cache()
    reset_cache_stats()
    yield
    clear_ann_window_cache()
    reset_cache_stats()


class TestANNWindowCache:
    """Test ANN window vector cache."""
    
    def test_cache_disabled_by_default(self):
        """Test that cache is disabled when flag not set."""
        # Without ENABLE_ANN_WINDOW_CACHE, should return None
        result = get_ann_windows(
            "NIFTY", "this_week", "0", 60, 100, "cosine", 60, ("file1.csv",)
        )
        assert result is None
    
    @patch.dict(os.environ, {"ENABLE_ANN_WINDOW_CACHE": "1"})
    def test_cache_miss(self):
        """Test cache miss returns None."""
        result = get_ann_windows(
            "NIFTY", "this_week", "0", 60, 100, "cosine", 60, ("file1.csv",)
        )
        assert result is None
        
        stats = get_ann_window_cache_stats()
        assert stats['hits'] == 0
        assert stats['misses'] == 1
    
    @patch.dict(os.environ, {"ENABLE_ANN_WINDOW_CACHE": "1"})
    def test_cache_hit(self):
        """Test cache hit returns stored data."""
        ann_windows = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        ann_day_map = [Path("day1.csv"), Path("day2.csv")]
        
        # Store in cache
        put_ann_windows(
            "NIFTY", "this_week", "0", 60, 100, "cosine", 60, 
            ("file1.csv",), ann_windows, ann_day_map
        )
        
        # Retrieve from cache
        result = get_ann_windows(
            "NIFTY", "this_week", "0", 60, 100, "cosine", 60, ("file1.csv",)
        )
        
        assert result is not None
        assert result['ann_windows'] == ann_windows
        assert len(result['ann_day_map']) == 2
        
        stats = get_ann_window_cache_stats()
        assert stats['hits'] == 1
        assert stats['size'] == 1
    
    def test_cache_eviction(self):
        """Test LRU eviction when cache exceeds max size."""
        # Patch the max size constant directly during test
        import src.path_forecast.ann_cache as cache_module
        original_max = cache_module._ANN_WINDOW_CACHE_MAX_SIZE
        
        try:
            # Set max size to 2
            cache_module._ANN_WINDOW_CACHE_MAX_SIZE = 2
            
            with patch.dict(os.environ, {"ENABLE_ANN_WINDOW_CACHE": "1"}):
                # Fill cache with 3 entries when max is 2
                for i in range(3):
                    put_ann_windows(
                        "NIFTY", "this_week", "0", 60, 100 + i, "cosine", 60, 
                        (f"file{i}.csv",), [[float(i)]], [Path(f"day{i}.csv")]
                    )
                
                stats = get_ann_window_cache_stats()
                assert stats['size'] == 2  # Should be limited to max size
                assert stats['evictions'] >= 1  # At least one eviction
        finally:
            # Restore original max size
            cache_module._ANN_WINDOW_CACHE_MAX_SIZE = original_max
    
    @patch.dict(os.environ, {"ENABLE_ANN_WINDOW_CACHE": "1"})
    def test_cache_key_uniqueness(self):
        """Test that different parameters create different cache keys."""
        ann_windows1 = [[1.0, 2.0]]
        ann_windows2 = [[3.0, 4.0]]
        
        # Store with different windows
        put_ann_windows(
            "NIFTY", "this_week", "0", 60, 100, "cosine", 60,
            ("file1.csv",), ann_windows1, [Path("day1.csv")]
        )
        
        put_ann_windows(
            "NIFTY", "this_week", "0", 90, 100, "cosine", 60,  # Different window
            ("file1.csv",), ann_windows2, [Path("day2.csv")]
        )
        
        # Retrieve should get correct values
        result1 = get_ann_windows(
            "NIFTY", "this_week", "0", 60, 100, "cosine", 60, ("file1.csv",)
        )
        result2 = get_ann_windows(
            "NIFTY", "this_week", "0", 90, 100, "cosine", 60, ("file1.csv",)
        )
        
        assert result1['ann_windows'] == ann_windows1
        assert result2['ann_windows'] == ann_windows2


class TestANNDiskCache:
    """Test ANN disk cache."""
    
    def test_disk_cache_disabled_by_default(self):
        """Test that disk cache is disabled when flag not set."""
        result = load_ann_index_from_disk(
            "NIFTY", "this_week", "0", 60, "cosine", 60
        )
        assert result is None
    
    @patch.dict(os.environ, {"ENABLE_ANN_DISK_CACHE": "1"})
    def test_disk_cache_no_dir(self):
        """Test disk cache returns None when directory not configured."""
        result = load_ann_index_from_disk(
            "NIFTY", "this_week", "0", 60, "cosine", 60
        )
        assert result is None
    
    @patch.dict(os.environ, {"ENABLE_ANN_DISK_CACHE": "1"})
    def test_disk_cache_save_and_load(self):
        """Test saving and loading from disk cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ANN_CACHE_DIR": tmpdir}):
                # Create mock ANN index
                mock_index = {"data": "test_index"}
                mock_day_map = [Path("day1.csv"), Path("day2.csv")]
                
                # Save to disk
                success = save_ann_index_to_disk(
                    "NIFTY", "this_week", "0", 60, "cosine", 60,
                    mock_index, mock_day_map, 1024, "model_v1"
                )
                assert success
                
                # Load from disk
                result = load_ann_index_from_disk(
                    "NIFTY", "this_week", "0", 60, "cosine", 60, "model_v1"
                )
                
                assert result is not None
                assert result['ann_index'] == mock_index
                assert len(result['ann_day_map']) == 2
                assert 'metadata' in result
                assert result['metadata']['index'] == "NIFTY"
                assert result['metadata']['model_id'] == "model_v1"
                assert 'load_ms' in result
                
                stats = get_ann_disk_cache_stats()
                assert stats['hits'] == 1
                assert stats['saves'] == 1
    
    @patch.dict(os.environ, {"ENABLE_ANN_DISK_CACHE": "1"})
    def test_disk_cache_versioning(self):
        """Test that different model versions are cached separately."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ANN_CACHE_DIR": tmpdir}):
                # Save two different versions
                save_ann_index_to_disk(
                    "NIFTY", "this_week", "0", 60, "cosine", 60,
                    {"version": 1}, [], model_id="v1"
                )
                save_ann_index_to_disk(
                    "NIFTY", "this_week", "0", 60, "cosine", 60,
                    {"version": 2}, [], model_id="v2"
                )
                
                # Load both versions
                result1 = load_ann_index_from_disk(
                    "NIFTY", "this_week", "0", 60, "cosine", 60, "v1"
                )
                result2 = load_ann_index_from_disk(
                    "NIFTY", "this_week", "0", 60, "cosine", 60, "v2"
                )
                
                assert result1['ann_index']['version'] == 1
                assert result2['ann_index']['version'] == 2


class TestCacheStats:
    """Test cache statistics."""
    
    @patch.dict(os.environ, {"ENABLE_ANN_WINDOW_CACHE": "1"})
    def test_hit_ratio_calculation(self):
        """Test that hit ratio is calculated correctly."""
        # Initial: no hits or misses
        stats = get_ann_window_cache_stats()
        assert stats['hit_ratio'] == 0.0
        
        # One miss
        get_ann_windows("NIFTY", "this_week", "0", 60, 100, "cosine", 60, ("file1.csv",))
        stats = get_ann_window_cache_stats()
        assert stats['hit_ratio'] == 0.0
        
        # Store and hit
        put_ann_windows(
            "NIFTY", "this_week", "0", 60, 100, "cosine", 60,
            ("file1.csv",), [[1.0]], [Path("day1.csv")]
        )
        get_ann_windows("NIFTY", "this_week", "0", 60, 100, "cosine", 60, ("file1.csv",))
        
        stats = get_ann_window_cache_stats()
        # 1 hit, 1 miss = 0.5 hit ratio
        assert 0.4 <= stats['hit_ratio'] <= 0.6
    
    def test_disk_cache_stats_no_activity(self):
        """Test disk cache stats with no activity."""
        stats = get_ann_disk_cache_stats()
        assert stats['hits'] == 0
        assert stats['misses'] == 0
        assert stats['saves'] == 0
        assert stats['hit_ratio'] == 0.0


def test_cache_clear():
    """Test that cache clear removes all entries."""
    with patch.dict(os.environ, {"ENABLE_ANN_WINDOW_CACHE": "1"}):
        # Add some entries
        put_ann_windows(
            "NIFTY", "this_week", "0", 60, 100, "cosine", 60,
            ("file1.csv",), [[1.0]], [Path("day1.csv")]
        )
        
        stats = get_ann_window_cache_stats()
        assert stats['size'] > 0
        
        # Clear cache
        clear_ann_window_cache()
        
        stats = get_ann_window_cache_stats()
        assert stats['size'] == 0
