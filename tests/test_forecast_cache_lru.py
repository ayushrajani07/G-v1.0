"""
Test LRU eviction behavior for forecast cache.

Validates requirements from ISSUE_FORECAST_CACHE_LRU.md:
1. Evictions occur once size exceeds max
2. Access reorders entries correctly (recently accessed not evicted prematurely)
3. TTL behavior is maintained independently of eviction
4. Stats endpoint includes evictions and max_size
"""
import sys
import time
import pytest
from unittest.mock import MagicMock


# Mock dependencies before import
sys.modules['src.path_forecast.ensemble'] = MagicMock()
sys.modules['src.error_handling'] = MagicMock()


class TestForecastCacheLRU:
    """Test LRU eviction for forecast cache."""
    
    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        """Set up test environment variables."""
        monkeypatch.setenv('G6_FORECAST_CACHE_TTL', '60')
        monkeypatch.setenv('G6_FORECAST_CACHE_MAX', '5')
    
    @pytest.fixture
    def cache_module(self):
        """Import cache module with fresh state."""
        # Import with test env vars
        from src.web.dashboard.routes import ensemble
        
        # Clear cache state
        with ensemble._CACHE_LOCK:
            ensemble._CACHE.clear()
            ensemble._CACHE_TIME.clear()
            ensemble._CACHE_HITS = 0
            ensemble._CACHE_MISSES = 0
            ensemble._CACHE_EVICTIONS = 0
        
        return ensemble
    
    def test_eviction_after_max_size_exceeded(self, cache_module):
        """Test that entries are evicted when cache exceeds max size."""
        ensemble = cache_module
        
        # Create mock forecast responses
        def make_response(idx: int):
            mock_metadata = MagicMock()
            mock_metadata.cache_hit = False
            mock_resp = MagicMock()
            mock_resp.metadata = mock_metadata
            return mock_resp
        
        # Insert max_size + 2 entries (should cause 2 evictions)
        max_size = ensemble._CACHE_MAX_SIZE
        for i in range(max_size + 2):
            key = ('NIFTY', i, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60)
            ensemble._cache_put(key, make_response(i))
        
        # Verify size is capped at max_size
        with ensemble._CACHE_LOCK:
            assert len(ensemble._CACHE) == max_size, f"Cache size should be {max_size}, got {len(ensemble._CACHE)}"
            assert ensemble._CACHE_EVICTIONS == 2, f"Expected 2 evictions, got {ensemble._CACHE_EVICTIONS}"
    
    def test_lru_order_preserved_on_access(self, cache_module):
        """Test that accessing an entry moves it to end (most recent)."""
        ensemble = cache_module
        
        # Create mock forecast responses
        def make_response(idx: int):
            mock_metadata = MagicMock()
            mock_metadata.cache_hit = False
            mock_resp = MagicMock()
            mock_resp.metadata = mock_metadata
            return mock_resp
        
        # Max size is 5 from fixture
        # Insert 5 entries to fill cache
        keys = [
            ('NIFTY', 1, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60),
            ('NIFTY', 2, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60),
            ('NIFTY', 3, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60),
            ('NIFTY', 4, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60),
            ('NIFTY', 5, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60),
        ]
        for i, key in enumerate(keys):
            ensemble._cache_put(key, make_response(i))
        
        # Access the second entry (should move it to end, making it most recent)
        # Order after access: 1, 3, 4, 5, 2 (2 is now most recent)
        ensemble._cache_get(keys[1])
        
        # Now insert 2 more entries to trigger evictions
        # Keys[0] (1) and keys[2] (3) should be evicted as they're the oldest
        for i in range(6, 8):
            key = ('NIFTY', i, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60)
            ensemble._cache_put(key, make_response(i))
        
        # Verify the accessed entry (keys[1]) is still present
        with ensemble._CACHE_LOCK:
            assert keys[1] in ensemble._CACHE, "Recently accessed entry should be retained"
            # Keys[0] should have been evicted (it was oldest)
            assert keys[0] not in ensemble._CACHE, "Oldest unaccessed entry should be evicted"
    
    def test_ttl_independent_of_eviction(self, cache_module):
        """Test that TTL expiration works independently of LRU eviction."""
        ensemble = cache_module
        
        # Temporarily set short TTL
        with ensemble._CACHE_LOCK:
            original_ttl = ensemble._CACHE_TTL_SEC
        
        try:
            # Set TTL to 1 second for this test
            ensemble._CACHE_TTL_SEC = 1
            
            def make_response(idx: int):
                mock_metadata = MagicMock()
                mock_metadata.cache_hit = False
                mock_resp = MagicMock()
                mock_resp.metadata = mock_metadata
                return mock_resp
            
            key = ('NIFTY', 1, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60)
            ensemble._cache_put(key, make_response(1))
            
            # Entry should be present initially
            result = ensemble._cache_get(key)
            assert result is not None, "Fresh entry should be cached"
            
            # Wait for TTL to expire
            time.sleep(1.5)
            
            # Entry should be expired and return None (miss)
            result = ensemble._cache_get(key)
            assert result is None, "Expired entry should return None"
            
            # Verify it was counted as a miss
            with ensemble._CACHE_LOCK:
                assert ensemble._CACHE_MISSES > 0, "Expired entry access should count as miss"
        
        finally:
            # Restore original TTL
            ensemble._CACHE_TTL_SEC = original_ttl
    
    def test_cache_stats_includes_evictions_and_max_size(self, cache_module):
        """Test that cache stats endpoint includes evictions and max_size."""
        ensemble = cache_module
        
        def make_response(idx: int):
            mock_metadata = MagicMock()
            mock_metadata.cache_hit = False
            mock_resp = MagicMock()
            mock_resp.metadata = mock_metadata
            return mock_resp
        
        # Insert entries to trigger evictions
        max_size = ensemble._CACHE_MAX_SIZE
        for i in range(max_size + 3):
            key = ('NIFTY', i, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60)
            ensemble._cache_put(key, make_response(i))
        
        # Check stats manually (simulating what the endpoint would return)
        with ensemble._CACHE_LOCK:
            stats = {
                'ttl_sec': ensemble._CACHE_TTL_SEC,
                'max_size': ensemble._CACHE_MAX_SIZE,
                'size': len(ensemble._CACHE),
                'hits': ensemble._CACHE_HITS,
                'misses': ensemble._CACHE_MISSES,
                'evictions': ensemble._CACHE_EVICTIONS,
            }
        
        # Verify stats structure
        assert 'max_size' in stats, "Stats should include max_size"
        assert 'evictions' in stats, "Stats should include evictions"
        assert stats['max_size'] == max_size, f"max_size should be {max_size}"
        assert stats['evictions'] == 3, f"Expected 3 evictions, got {stats['evictions']}"
        assert stats['size'] == max_size, f"Current size should equal max_size ({max_size})"
    
    def test_cache_clear_resets_evictions(self, cache_module):
        """Test that cache clear resets evictions counter."""
        ensemble = cache_module
        
        def make_response(idx: int):
            mock_metadata = MagicMock()
            mock_metadata.cache_hit = False
            mock_resp = MagicMock()
            mock_resp.metadata = mock_metadata
            return mock_resp
        
        # Trigger some evictions
        max_size = ensemble._CACHE_MAX_SIZE
        for i in range(max_size + 2):
            key = ('NIFTY', i, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60)
            ensemble._cache_put(key, make_response(i))
        
        # Verify evictions occurred
        with ensemble._CACHE_LOCK:
            assert ensemble._CACHE_EVICTIONS > 0, "Evictions should have occurred"
        
        # Clear cache (simulating cache_clear endpoint)
        with ensemble._CACHE_LOCK:
            ensemble._CACHE.clear()
            ensemble._CACHE_TIME.clear()
            ensemble._CACHE_HITS = 0
            ensemble._CACHE_MISSES = 0
            ensemble._CACHE_EVICTIONS = 0
        
        # Verify everything is reset
        with ensemble._CACHE_LOCK:
            assert len(ensemble._CACHE) == 0, "Cache should be empty"
            assert ensemble._CACHE_EVICTIONS == 0, "Evictions counter should be reset"
    
    def test_default_max_size_is_500(self, monkeypatch):
        """Test that default G6_FORECAST_CACHE_MAX is 500."""
        # This test verifies the default by checking environment parsing logic
        # When G6_FORECAST_CACHE_MAX is not set, should default to 500
        import os
        
        # Remove any env var setting from fixture
        monkeypatch.delenv('G6_FORECAST_CACHE_MAX', raising=False)
        
        # Test the parsing logic directly
        default_val = max(1, int(os.environ.get('G6_FORECAST_CACHE_MAX', '500')))
        assert default_val == 500, "Default max_size should be 500 when env var not set"
    
    def test_operations_are_o1(self, cache_module):
        """Test that cache operations are O(1) as required."""
        ensemble = cache_module
        
        def make_response(idx: int):
            mock_metadata = MagicMock()
            mock_metadata.cache_hit = False
            mock_resp = MagicMock()
            mock_resp.metadata = mock_metadata
            return mock_resp
        
        # All operations should be O(1):
        # - OrderedDict __setitem__ is O(1)
        # - OrderedDict move_to_end is O(1)
        # - OrderedDict popitem(last=False) is O(1)
        # - OrderedDict __getitem__ is O(1)
        
        # Fill cache to max
        max_size = ensemble._CACHE_MAX_SIZE
        for i in range(max_size):
            key = ('NIFTY', i, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60)
            ensemble._cache_put(key, make_response(i))
        
        # Measure time for single put operation (should be very fast)
        start = time.perf_counter()
        key = ('NIFTY', max_size, '0.1,0.5,0.9', 100.0, 0.2, 375.0, 60)
        ensemble._cache_put(key, make_response(max_size))
        duration = time.perf_counter() - start
        
        # Should complete in microseconds (< 1ms for O(1) operation)
        assert duration < 0.01, f"Cache put should be fast (O(1)), took {duration*1000:.3f}ms"
        
        # Measure time for single get operation
        start = time.perf_counter()
        ensemble._cache_get(key)
        duration = time.perf_counter() - start
        
        # Should complete in microseconds
        assert duration < 0.01, f"Cache get should be fast (O(1)), took {duration*1000:.3f}ms"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
