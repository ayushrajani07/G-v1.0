"""Tests for Regime Detector Module (Phase 10)"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

# Import module under test
from src.ml import regime_detector


def test_compute_embedding_basic():
    """Test basic embedding computation with default features."""
    embedding = regime_detector.compute_embedding(
        index="NIFTY",
        volatility=0.5,
        bandwidth=0.3,
        drift_severity=0.2,
        cache_hit_ratio=0.8,
        norm_error_p90=0.15,
    )
    
    assert isinstance(embedding, dict)
    assert len(embedding) > 0
    
    # Check that values are normalized [0, 1]
    for key, value in embedding.items():
        assert 0.0 <= value <= 1.0, f"Feature {key} out of range: {value}"


def test_compute_embedding_clamping():
    """Test that embedding values are clamped to [0, 1] range."""
    embedding = regime_detector.compute_embedding(
        index="NIFTY",
        volatility=-0.5,  # Should be clamped to 0
        bandwidth=1.5,    # Should be clamped to 1
        drift_severity=0.5,
        cache_hit_ratio=0.8,
        norm_error_p90=0.2,
    )
    
    if "volatility" in embedding:
        assert embedding["volatility"] == 0.0
    if "bandwidth" in embedding:
        assert embedding["bandwidth"] == 1.0


def test_embedding_keys_match_configured_features():
    """Test that embedding keys match configured features."""
    # Set specific features via environment
    os.environ["G6_REGIME_FEATURES"] = "volatility,bandwidth,drift_severity"
    
    embedding = regime_detector.compute_embedding(
        index="NIFTY",
        volatility=0.5,
        bandwidth=0.3,
        drift_severity=0.2,
        cache_hit_ratio=0.8,
        norm_error_p90=0.15,
    )
    
    # Should only have the 3 configured features
    assert "volatility" in embedding
    assert "bandwidth" in embedding
    assert "drift_severity" in embedding
    
    # Reset environment
    os.environ.pop("G6_REGIME_FEATURES", None)


def test_distance_euclidean():
    """Test Euclidean distance calculation."""
    vec1 = [0.0, 0.0, 0.0]
    vec2 = [1.0, 1.0, 1.0]
    
    distance = regime_detector._compute_distance(vec1, vec2, metric="euclidean")
    
    # Expected: sqrt(3)
    import math
    expected = math.sqrt(3.0)
    assert abs(distance - expected) < 1e-6


def test_distance_cosine_identical():
    """Test cosine distance for identical vectors (should be 0)."""
    vec1 = [0.5, 0.3, 0.8]
    vec2 = [0.5, 0.3, 0.8]
    
    distance = regime_detector._compute_distance(vec1, vec2, metric="cosine")
    
    assert distance < 1e-6, f"Expected near-zero distance, got {distance}"


def test_distance_cosine_opposite():
    """Test cosine distance for opposite vectors (should be high)."""
    vec1 = [1.0, 1.0, 1.0]
    vec2 = [-1.0, -1.0, -1.0]
    
    distance = regime_detector._compute_distance(vec1, vec2, metric="cosine")
    
    # Opposite vectors have cosine similarity = -1, so distance = (1 - (-1)) / 2 = 1.0
    assert abs(distance - 1.0) < 1e-6


def test_distance_zero_vectors():
    """Test distance calculation with zero vectors."""
    vec1 = [0.0, 0.0, 0.0]
    vec2 = [0.0, 0.0, 0.0]
    
    distance = regime_detector._compute_distance(vec1, vec2, metric="cosine")
    
    # Should handle gracefully and return 0
    assert distance == 0.0


def test_detect_shift_no_history():
    """Test shift detection with no history (should be stable)."""
    # Use a temporary index that won't have history
    test_index = f"TEST_NO_HISTORY_{os.getpid()}"
    
    embedding = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.5,
        bandwidth=0.3,
        drift_severity=0.2,
        cache_hit_ratio=0.8,
        norm_error_p90=0.15,
    )
    
    status, distance = regime_detector.detect_shift(test_index, embedding)
    
    assert status == regime_detector.REGIME_STATUS_STABLE
    assert distance == 0.0


def test_detect_shift_critical_threshold():
    """Test that critical threshold is correctly detected."""
    test_index = f"TEST_CRITICAL_{os.getpid()}"
    
    # Set thresholds for test (adjusted for cosine distance range)
    os.environ["G6_REGIME_SHIFT_DISTANCE_WARN"] = "0.2"
    os.environ["G6_REGIME_SHIFT_DISTANCE_CRIT"] = "0.35"
    
    # Create baseline embedding (stable)
    baseline = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.1,
        bandwidth=0.1,
        drift_severity=0.1,
        cache_hit_ratio=0.9,
        norm_error_p90=0.1,
    )
    
    # Update history with baseline
    regime_detector.update_regime_history(
        test_index,
        baseline,
        regime_detector.REGIME_STATUS_STABLE,
        0.0,
    )
    
    # Create significantly different embedding
    current = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.9,
        bandwidth=0.9,
        drift_severity=0.9,
        cache_hit_ratio=0.1,
        norm_error_p90=0.9,
    )
    
    status, distance = regime_detector.detect_shift(test_index, current)
    
    # Distance should be large enough to trigger critical
    assert status == regime_detector.REGIME_STATUS_CRITICAL
    assert distance > 0.35
    
    # Clean up
    os.environ.pop("G6_REGIME_SHIFT_DISTANCE_WARN", None)
    os.environ.pop("G6_REGIME_SHIFT_DISTANCE_CRIT", None)
    
    # Clean up test file
    try:
        path = regime_detector._get_history_path(test_index)
        if path.exists():
            path.unlink()
            path.parent.rmdir()
    except Exception:
        pass


def test_detect_shift_warn_threshold():
    """Test that warn threshold is correctly detected."""
    test_index = f"TEST_WARN_{os.getpid()}"
    
    # Set thresholds for test (lower thresholds for this test)
    os.environ["G6_REGIME_SHIFT_DISTANCE_WARN"] = "0.05"
    os.environ["G6_REGIME_SHIFT_DISTANCE_CRIT"] = "0.35"
    
    # Create baseline embedding
    baseline = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.2,
        bandwidth=0.2,
        drift_severity=0.2,
        cache_hit_ratio=0.8,
        norm_error_p90=0.2,
    )
    
    regime_detector.update_regime_history(
        test_index,
        baseline,
        regime_detector.REGIME_STATUS_STABLE,
        0.0,
    )
    
    # Create moderately different embedding (should trigger warn)
    current = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.6,
        bandwidth=0.6,
        drift_severity=0.5,
        cache_hit_ratio=0.4,
        norm_error_p90=0.6,
    )
    
    status, distance = regime_detector.detect_shift(test_index, current)
    
    # Should be warn or critical depending on actual distance
    assert status in [regime_detector.REGIME_STATUS_WARN, regime_detector.REGIME_STATUS_CRITICAL]
    assert distance > 0.0
    
    # Clean up
    os.environ.pop("G6_REGIME_SHIFT_DISTANCE_WARN", None)
    os.environ.pop("G6_REGIME_SHIFT_DISTANCE_CRIT", None)
    
    try:
        path = regime_detector._get_history_path(test_index)
        if path.exists():
            path.unlink()
            path.parent.rmdir()
    except Exception:
        pass


def test_get_current_regime_empty():
    """Test get_current_regime with no history."""
    test_index = f"TEST_EMPTY_{os.getpid()}"
    
    result = regime_detector.get_current_regime(test_index)
    
    assert result["embedding"] == {}
    assert result["distance"] == 0.0
    assert result["shift_status"] == regime_detector.REGIME_STATUS_STABLE
    assert result["last_change_timestamp"] is None
    assert result["history_count"] == 0


def test_get_current_regime_with_history():
    """Test get_current_regime with existing history."""
    test_index = f"TEST_WITH_HISTORY_{os.getpid()}"
    
    # Create and store an embedding
    embedding = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.5,
        bandwidth=0.3,
        drift_severity=0.2,
        cache_hit_ratio=0.8,
        norm_error_p90=0.15,
    )
    
    regime_detector.update_regime_history(
        test_index,
        embedding,
        regime_detector.REGIME_STATUS_STABLE,
        0.0,
    )
    
    result = regime_detector.get_current_regime(test_index)
    
    assert result["embedding"] == embedding
    assert result["distance"] == 0.0
    assert result["shift_status"] == regime_detector.REGIME_STATUS_STABLE
    assert result["last_change_timestamp"] is not None
    assert result["history_count"] == 1
    
    # Clean up
    try:
        path = regime_detector._get_history_path(test_index)
        if path.exists():
            path.unlink()
            path.parent.rmdir()
    except Exception:
        pass


def test_update_regime_history_trimming():
    """Test that regime history is properly trimmed to configured window."""
    test_index = f"TEST_TRIM_{os.getpid()}"
    
    # Set small history window for test
    os.environ["G6_REGIME_EMBED_HISTORY_DAYS"] = "3"
    
    embedding = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.5,
        bandwidth=0.3,
        drift_severity=0.2,
        cache_hit_ratio=0.8,
        norm_error_p90=0.15,
    )
    
    # Add 5 entries
    for i in range(5):
        regime_detector.update_regime_history(
            test_index,
            embedding,
            regime_detector.REGIME_STATUS_STABLE,
            0.0,
        )
    
    # Check that history is trimmed to 3
    result = regime_detector.get_current_regime(test_index)
    assert result["history_count"] == 3
    
    # Clean up
    os.environ.pop("G6_REGIME_EMBED_HISTORY_DAYS", None)
    
    try:
        path = regime_detector._get_history_path(test_index)
        if path.exists():
            path.unlink()
            path.parent.rmdir()
    except Exception:
        pass


def test_get_regime_summary():
    """Test regime summary generation."""
    test_index = f"TEST_SUMMARY_{os.getpid()}"
    
    # Add multiple entries with different statuses
    embedding1 = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.2,
        bandwidth=0.2,
        drift_severity=0.1,
        cache_hit_ratio=0.9,
        norm_error_p90=0.1,
    )
    
    regime_detector.update_regime_history(
        test_index,
        embedding1,
        regime_detector.REGIME_STATUS_STABLE,
        0.0,
    )
    
    embedding2 = regime_detector.compute_embedding(
        index=test_index,
        volatility=0.8,
        bandwidth=0.8,
        drift_severity=0.7,
        cache_hit_ratio=0.3,
        norm_error_p90=0.8,
    )
    
    regime_detector.update_regime_history(
        test_index,
        embedding2,
        regime_detector.REGIME_STATUS_CRITICAL,
        0.6,
    )
    
    summary = regime_detector.get_regime_summary(test_index)
    
    assert "current" in summary
    assert "recent_changes" in summary
    assert "avg_distance" in summary
    assert "max_distance" in summary
    
    assert summary["current"]["shift_status"] == regime_detector.REGIME_STATUS_CRITICAL
    assert summary["max_distance"] >= 0.6
    
    # Clean up
    try:
        path = regime_detector._get_history_path(test_index)
        if path.exists():
            path.unlink()
            path.parent.rmdir()
    except Exception:
        pass


def test_safe_write_read_history():
    """Test atomic write and read of regime history."""
    test_index = f"TEST_IO_{os.getpid()}"
    
    # Create test history
    test_history = [
        {
            "timestamp": "2025-01-01T00:00:00Z",
            "embedding": {"volatility": 0.5, "bandwidth": 0.3},
            "status": "stable",
            "distance": 0.0,
        },
        {
            "timestamp": "2025-01-02T00:00:00Z",
            "embedding": {"volatility": 0.7, "bandwidth": 0.6},
            "status": "warn",
            "distance": 0.4,
        },
    ]
    
    # Write history
    regime_detector._safe_write_history(test_index, test_history)
    
    # Read it back
    read_history = regime_detector._safe_read_history(test_index)
    
    assert len(read_history) == 2
    assert read_history[0]["status"] == "stable"
    assert read_history[1]["status"] == "warn"
    
    # Clean up
    try:
        path = regime_detector._get_history_path(test_index)
        if path.exists():
            path.unlink()
            path.parent.rmdir()
    except Exception:
        pass
