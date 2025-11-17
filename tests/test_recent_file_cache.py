"""
Tests for Recent Window File Cache.

Validates that the file-level cache for recent TP window reduces disk I/O
and correctly handles TTL, mtime invalidation, and eviction.
"""
from __future__ import annotations

import csv
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def temp_csv_dir(tmp_path):
    """Create temporary CSV directory structure for testing."""
    root = tmp_path / "data" / "g6_data"
    index_dir = root / "NIFTY" / "this_month" / "0"
    index_dir.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def sample_csv(temp_csv_dir):
    """Create a sample CSV file with TP data."""
    today = time.strftime('%Y-%m-%d')
    csv_path = temp_csv_dir / "NIFTY" / "this_month" / "0" / f"{today}.csv"
    
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'tp', 'ce_iv', 'pe_iv'])
        for i in range(100):
            writer.writerow([f'2025-11-17 09:{i:02d}:00', 18000 + i, 0.15, 0.16])
    
    return csv_path


@pytest.fixture
def app_with_mock_data(temp_csv_dir, sample_csv, monkeypatch):
    """Create FastAPI app with mocked data directory."""
    from src.web.dashboard.routes import ensemble
    
    # Mock _project_root to return our temp directory
    def mock_project_root():
        return temp_csv_dir.parent.parent
    
    monkeypatch.setattr(ensemble, '_project_root', mock_project_root)
    
    # Clear cache before each test
    with ensemble._RECENT_FILE_CACHE_LOCK:
        ensemble._RECENT_FILE_CACHE.clear()
        ensemble._RECENT_FILE_CACHE_HITS = 0
        ensemble._RECENT_FILE_CACHE_MISSES = 0
    
    return ensemble


def test_cache_miss_on_first_load(app_with_mock_data):
    """Test that first load results in cache miss."""
    ensemble = app_with_mock_data
    
    # First call should be a miss
    initial_misses = ensemble._RECENT_FILE_CACHE_MISSES
    rows = ensemble._load_recent_window('NIFTY', 10)
    
    assert len(rows) == 10
    assert ensemble._RECENT_FILE_CACHE_MISSES == initial_misses + 1
    assert ensemble._RECENT_FILE_CACHE_HITS == 0


def test_cache_hit_on_second_load(app_with_mock_data):
    """Test that second identical load results in cache hit."""
    ensemble = app_with_mock_data
    
    # First call - miss
    rows1 = ensemble._load_recent_window('NIFTY', 10)
    initial_hits = ensemble._RECENT_FILE_CACHE_HITS
    
    # Second call with same params - should hit
    rows2 = ensemble._load_recent_window('NIFTY', 10)
    
    assert len(rows1) == len(rows2)
    assert rows1 == rows2
    assert ensemble._RECENT_FILE_CACHE_HITS == initial_hits + 1


def test_cache_reuses_larger_window(app_with_mock_data):
    """Test that cache can reuse larger window for smaller request."""
    ensemble = app_with_mock_data
    
    # Load 50 rows
    rows_50 = ensemble._load_recent_window('NIFTY', 50)
    assert len(rows_50) == 50
    
    initial_hits = ensemble._RECENT_FILE_CACHE_HITS
    
    # Request 10 rows - should hit cache and slice
    rows_10 = ensemble._load_recent_window('NIFTY', 10)
    
    assert len(rows_10) == 10
    assert ensemble._RECENT_FILE_CACHE_HITS == initial_hits + 1
    # The 10 rows should match the last 10 of the 50
    assert rows_10 == rows_50[-10:]


def test_cache_invalidation_on_mtime_change(app_with_mock_data, sample_csv):
    """Test that cache invalidates when file mtime changes."""
    ensemble = app_with_mock_data
    
    # First load
    rows1 = ensemble._load_recent_window('NIFTY', 10)
    assert ensemble._RECENT_FILE_CACHE_HITS == 0
    
    # Second load - should hit
    rows2 = ensemble._load_recent_window('NIFTY', 10)
    assert ensemble._RECENT_FILE_CACHE_HITS == 1
    
    # Modify file (touch to change mtime)
    time.sleep(0.01)  # Ensure mtime difference
    sample_csv.touch()
    
    initial_misses = ensemble._RECENT_FILE_CACHE_MISSES
    
    # Third load - should miss due to mtime change
    rows3 = ensemble._load_recent_window('NIFTY', 10)
    assert ensemble._RECENT_FILE_CACHE_MISSES == initial_misses + 1


def test_cache_ttl_expiry(app_with_mock_data, monkeypatch):
    """Test that cache expires after TTL."""
    ensemble = app_with_mock_data
    
    # Set short TTL
    monkeypatch.setattr(ensemble, '_RECENT_FILE_CACHE_TTL_SEC', 1)
    
    # First load
    rows1 = ensemble._load_recent_window('NIFTY', 10)
    assert ensemble._RECENT_FILE_CACHE_MISSES == 1
    
    # Immediate second load - should hit
    rows2 = ensemble._load_recent_window('NIFTY', 10)
    assert ensemble._RECENT_FILE_CACHE_HITS == 1
    
    # Wait for TTL to expire
    time.sleep(1.1)
    
    initial_misses = ensemble._RECENT_FILE_CACHE_MISSES
    
    # Third load - should miss due to TTL expiry
    rows3 = ensemble._load_recent_window('NIFTY', 10)
    assert ensemble._RECENT_FILE_CACHE_MISSES == initial_misses + 1


def test_cache_eviction_when_full(app_with_mock_data, temp_csv_dir, monkeypatch):
    """Test that cache evicts oldest entry when max size reached."""
    ensemble = app_with_mock_data
    
    # Set small max size
    monkeypatch.setattr(ensemble, '_RECENT_FILE_CACHE_MAX_SIZE', 2)
    
    # Create multiple index CSVs
    today = time.strftime('%Y-%m-%d')
    for index in ['INDEX1', 'INDEX2', 'INDEX3']:
        idx_dir = temp_csv_dir / index / "this_month" / "0"
        idx_dir.mkdir(parents=True, exist_ok=True)
        csv_path = idx_dir / f"{today}.csv"
        with csv_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['tp'])
            for i in range(10):
                writer.writerow([18000 + i])
    
    # Load first index
    ensemble._load_recent_window('INDEX1', 10)
    assert len(ensemble._RECENT_FILE_CACHE) == 1
    
    # Load second index
    ensemble._load_recent_window('INDEX2', 10)
    assert len(ensemble._RECENT_FILE_CACHE) == 2
    
    # Load third index - should evict oldest (INDEX1)
    ensemble._load_recent_window('INDEX3', 10)
    assert len(ensemble._RECENT_FILE_CACHE) == 2
    
    # Check that INDEX1 is no longer in cache
    cache_keys = list(ensemble._RECENT_FILE_CACHE.keys())
    index_names = [k[0] for k in cache_keys]
    assert 'INDEX1' not in index_names
    assert 'INDEX2' in index_names
    assert 'INDEX3' in index_names


def test_cache_disabled_when_ttl_zero(app_with_mock_data, monkeypatch):
    """Test that cache is disabled when TTL is set to 0."""
    ensemble = app_with_mock_data
    
    # Set TTL to 0 to disable caching
    monkeypatch.setattr(ensemble, '_RECENT_FILE_CACHE_TTL_SEC', 0)
    
    # First load
    rows1 = ensemble._load_recent_window('NIFTY', 10)
    
    # Second load - should not hit cache (cache disabled)
    initial_hits = ensemble._RECENT_FILE_CACHE_HITS
    rows2 = ensemble._load_recent_window('NIFTY', 10)
    
    assert ensemble._RECENT_FILE_CACHE_HITS == initial_hits  # No hits when disabled
    assert len(ensemble._RECENT_FILE_CACHE) == 0  # Cache should be empty


def test_cache_stats_endpoint(app_with_mock_data, monkeypatch):
    """Test that /cache/stats includes recent_file_cache statistics."""
    from src.web.dashboard.app import app as fastapi_app
    
    ensemble = app_with_mock_data
    client = TestClient(fastapi_app)
    
    # Load some data to populate cache
    ensemble._load_recent_window('NIFTY', 10)
    ensemble._load_recent_window('NIFTY', 10)  # Hit
    
    # Get cache stats
    response = client.get('/api/ml/ensemble/cache/stats')
    assert response.status_code == 200
    
    data = response.json()
    assert 'recent_file_cache' in data
    
    file_cache = data['recent_file_cache']
    assert 'hits' in file_cache
    assert 'misses' in file_cache
    assert 'current_entries' in file_cache
    assert 'ttl_sec' in file_cache
    assert 'max_size' in file_cache
    assert 'hit_ratio' in file_cache
    
    # Verify hit/miss tracking
    assert file_cache['hits'] >= 1
    assert file_cache['misses'] >= 1


def test_cache_clear_endpoint(app_with_mock_data, monkeypatch):
    """Test that /cache/clear clears recent_file_cache."""
    from src.web.dashboard.app import app as fastapi_app
    
    ensemble = app_with_mock_data
    client = TestClient(fastapi_app)
    
    # Populate cache
    ensemble._load_recent_window('NIFTY', 10)
    assert len(ensemble._RECENT_FILE_CACHE) > 0
    assert ensemble._RECENT_FILE_CACHE_HITS + ensemble._RECENT_FILE_CACHE_MISSES > 0
    
    # Clear cache
    response = client.post('/api/ml/ensemble/cache/clear')
    assert response.status_code == 200
    
    data = response.json()
    assert data['status'] == 'ok'
    assert 'recent_file_cache' in data.get('caches_cleared', [])
    
    # Verify cache is cleared
    assert len(ensemble._RECENT_FILE_CACHE) == 0
    assert ensemble._RECENT_FILE_CACHE_HITS == 0
    assert ensemble._RECENT_FILE_CACHE_MISSES == 0


def test_environment_variable_configuration(monkeypatch):
    """Test that environment variables configure cache behavior."""
    # Set environment variables
    monkeypatch.setenv('G6_RECENT_FILE_CACHE_TTL', '120')
    monkeypatch.setenv('G6_RECENT_FILE_CACHE_MAX_SIZE', '100')
    
    # Re-import to pick up env vars
    import importlib
    from src.web.dashboard.routes import ensemble
    importlib.reload(ensemble)
    
    assert ensemble._RECENT_FILE_CACHE_TTL_SEC == 120
    assert ensemble._RECENT_FILE_CACHE_MAX_SIZE == 100


def test_empty_limit_returns_empty_list(app_with_mock_data):
    """Test that limit <= 0 returns empty list without hitting cache."""
    ensemble = app_with_mock_data
    
    initial_misses = ensemble._RECENT_FILE_CACHE_MISSES
    rows = ensemble._load_recent_window('NIFTY', 0)
    
    assert rows == []
    # Should not count as miss since we skip cache lookup
    assert ensemble._RECENT_FILE_CACHE_MISSES == initial_misses


def test_missing_file_returns_empty_list(app_with_mock_data):
    """Test that missing CSV file returns empty list."""
    ensemble = app_with_mock_data
    
    rows = ensemble._load_recent_window('NONEXISTENT', 10)
    assert rows == []
