"""Regime Change Detection Module (Phase 10 - Regime Embedding & Detection)

Implements production-ready regime change detection using embeddings:
 - Daily regime embedding per index (volatility, bandwidth, drift, cache metrics, errors)
 - Rolling history persistence (default 30 days)
 - Distance metric (cosine or Euclidean) vs last stable regime centroid
 - Threshold-based status detection (stable|warn|critical)

Environment Variables:
 - G6_REGIME_EMBED_HISTORY_DAYS (default 30)
 - G6_REGIME_SHIFT_DISTANCE_WARN (default 0.35)
 - G6_REGIME_SHIFT_DISTANCE_CRIT (default 0.55)
 - G6_REGIME_WEEKLY_ENABLED (default 1)
 - G6_REGIME_FEATURES (comma list; default volatility,bandwidth,drift_severity,cache_hit_ratio,norm_error_p90)
 - G6_REGIME_DISTANCE_METRIC (default cosine; options: cosine, euclidean)
"""
from __future__ import annotations

import json
import os
import logging
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import math

_LOG = logging.getLogger(__name__)

# Environment variable defaults
_DEFAULT_HISTORY_DAYS = 30
_DEFAULT_DISTANCE_WARN = 0.35
_DEFAULT_DISTANCE_CRIT = 0.55
_DEFAULT_WEEKLY_ENABLED = 1
_DEFAULT_FEATURES = "volatility,bandwidth,drift_severity,cache_hit_ratio,norm_error_p90"
_DEFAULT_DISTANCE_METRIC = "cosine"

# Status constants
REGIME_STATUS_STABLE = "stable"
REGIME_STATUS_WARN = "warn"
REGIME_STATUS_CRITICAL = "critical"


def _get_env_int(name: str, default: int) -> int:
    """Get integer from environment variable with fallback to default."""
    try:
        return int(os.environ.get(name, str(default)).strip())
    except Exception:
        return default


def _get_env_float(name: str, default: float) -> float:
    """Get float from environment variable with fallback to default."""
    try:
        return float(os.environ.get(name, str(default)).strip())
    except Exception:
        return default


def _get_env_str(name: str, default: str) -> str:
    """Get string from environment variable with fallback to default."""
    return os.environ.get(name, default).strip()


def _get_regime_features() -> List[str]:
    """Parse G6_REGIME_FEATURES environment variable into list."""
    features_str = _get_env_str("G6_REGIME_FEATURES", _DEFAULT_FEATURES)
    return [f.strip() for f in features_str.split(",") if f.strip()]


def _get_history_path(index: str) -> Path:
    """Get path to regime history JSON file for given index."""
    # Use project root relative path
    project_root = Path(__file__).resolve().parents[2]
    history_dir = project_root / "data" / "regime" / index
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / "history.json"


def _safe_read_history(index: str) -> List[Dict[str, Any]]:
    """Read regime history from JSON file, return empty list if file doesn't exist or is invalid."""
    path = _get_history_path(index)
    if not path.exists():
        return []
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception as e:
        _LOG.warning(f"Failed to read regime history for {index}: {e}")
        return []


def _safe_write_history(index: str, history: List[Dict[str, Any]]) -> None:
    """Write regime history to JSON file atomically (temp file + replace)."""
    path = _get_history_path(index)
    
    try:
        # Write to temporary file first
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=path.parent,
            delete=False,
            suffix='.tmp'
        ) as tmp:
            json.dump(history, tmp, indent=2)
            tmp_path = tmp.name
        
        # Atomic replace
        os.replace(tmp_path, path)
        _LOG.debug(f"Wrote regime history for {index}: {len(history)} entries")
    
    except Exception as e:
        _LOG.error(f"Failed to write regime history for {index}: {e}")
        # Clean up temp file if it exists
        try:
            if 'tmp_path' in locals():
                os.unlink(tmp_path)
        except Exception:
            pass


def compute_embedding(
    index: str,
    volatility: float = 0.0,
    bandwidth: float = 0.0,
    drift_severity: float = 0.0,
    cache_hit_ratio: float = 0.0,
    norm_error_p90: float = 0.0,
) -> Dict[str, float]:
    """Compute regime embedding vector from provided feature values.
    
    Args:
        index: Index name (for logging)
        volatility: Normalized recent volatility metric (0-1 range)
        bandwidth: Average band width metric (0-1 range)
        drift_severity: Drift severity aggregate (0-1 range)
        cache_hit_ratio: Cache hit ratio (0-1 range)
        norm_error_p90: Normalized p90 error metric (0-1 range)
    
    Returns:
        Dictionary with feature names as keys and normalized values
    """
    features = _get_regime_features()
    embedding: Dict[str, float] = {}
    
    # Map feature names to values
    feature_values = {
        "volatility": volatility,
        "bandwidth": bandwidth,
        "drift_severity": drift_severity,
        "cache_hit_ratio": cache_hit_ratio,
        "norm_error_p90": norm_error_p90,
    }
    
    # Build embedding with only configured features
    for feature in features:
        if feature in feature_values:
            embedding[feature] = max(0.0, min(1.0, feature_values[feature]))
        else:
            _LOG.warning(f"Unknown regime feature '{feature}' for {index}, defaulting to 0.0")
            embedding[feature] = 0.0
    
    return embedding


def _embedding_to_vector(embedding: Dict[str, float]) -> List[float]:
    """Convert embedding dictionary to ordered vector list."""
    features = _get_regime_features()
    return [embedding.get(f, 0.0) for f in features]


def _compute_distance(vec1: List[float], vec2: List[float], metric: str = "cosine") -> float:
    """Compute distance between two vectors using specified metric.
    
    Args:
        vec1: First vector
        vec2: Second vector
        metric: Distance metric ('cosine' or 'euclidean')
    
    Returns:
        Distance value (0.0 = identical, higher = more different)
    """
    if len(vec1) != len(vec2):
        _LOG.error(f"Vector length mismatch: {len(vec1)} != {len(vec2)}")
        return 0.0
    
    if len(vec1) == 0:
        return 0.0
    
    if metric == "euclidean":
        # Euclidean distance: sqrt(sum((a-b)^2))
        squared_diff = sum((a - b) ** 2 for a, b in zip(vec1, vec2))
        return math.sqrt(squared_diff)
    
    elif metric == "cosine":
        # Cosine distance: 1 - cosine_similarity
        # cosine_similarity = dot(A,B) / (norm(A) * norm(B))
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        
        cosine_sim = dot_product / (norm1 * norm2)
        # Clamp to [-1, 1] to handle floating point errors
        cosine_sim = max(-1.0, min(1.0, cosine_sim))
        # Distance is 1 - similarity, range [0, 2]
        # Normalize to [0, 1] for consistency
        return (1.0 - cosine_sim) / 2.0
    
    else:
        _LOG.error(f"Unknown distance metric '{metric}', using cosine")
        return _compute_distance(vec1, vec2, "cosine")


def get_current_regime(index: str) -> Dict[str, Any]:
    """Get current regime status and embedding for given index.
    
    Returns:
        Dictionary with:
        - embedding: Dict of feature values
        - distance: Float distance from last stable centroid
        - shift_status: One of 'stable', 'warn', 'critical'
        - last_change_timestamp: ISO timestamp of last status change
        - history_count: Number of historical entries
    """
    history = _safe_read_history(index)
    
    if not history:
        return {
            "embedding": {},
            "distance": 0.0,
            "shift_status": REGIME_STATUS_STABLE,
            "last_change_timestamp": None,
            "history_count": 0,
        }
    
    # Get most recent entry
    latest = history[-1]
    embedding = latest.get("embedding", {})
    distance = latest.get("distance", 0.0)
    status = latest.get("status", REGIME_STATUS_STABLE)
    timestamp = latest.get("timestamp", None)
    
    return {
        "embedding": embedding,
        "distance": distance,
        "shift_status": status,
        "last_change_timestamp": timestamp,
        "history_count": len(history),
    }


def detect_shift(
    index: str,
    current_embedding: Dict[str, float],
) -> Tuple[str, float]:
    """Detect regime shift by comparing current embedding to historical baseline.
    
    Args:
        index: Index name
        current_embedding: Current regime embedding dictionary
    
    Returns:
        Tuple of (status, distance) where status is 'stable', 'warn', or 'critical'
    """
    history = _safe_read_history(index)
    
    # Threshold values from environment
    warn_threshold = _get_env_float("G6_REGIME_SHIFT_DISTANCE_WARN", _DEFAULT_DISTANCE_WARN)
    crit_threshold = _get_env_float("G6_REGIME_SHIFT_DISTANCE_CRIT", _DEFAULT_DISTANCE_CRIT)
    metric = _get_env_str("G6_REGIME_DISTANCE_METRIC", _DEFAULT_DISTANCE_METRIC)
    
    # If no history, consider stable with distance 0
    if not history:
        return REGIME_STATUS_STABLE, 0.0
    
    # Find last stable centroid (look backwards for stable status)
    stable_centroid = None
    for entry in reversed(history):
        if entry.get("status") == REGIME_STATUS_STABLE:
            stable_centroid = entry.get("embedding", {})
            break
    
    # If no stable centroid found, use the oldest entry as baseline
    if stable_centroid is None and history:
        stable_centroid = history[0].get("embedding", {})
    
    # If still no centroid, consider stable
    if not stable_centroid:
        return REGIME_STATUS_STABLE, 0.0
    
    # Compute distance
    current_vec = _embedding_to_vector(current_embedding)
    centroid_vec = _embedding_to_vector(stable_centroid)
    distance = _compute_distance(current_vec, centroid_vec, metric)
    
    # Determine status based on thresholds
    if distance >= crit_threshold:
        status = REGIME_STATUS_CRITICAL
    elif distance >= warn_threshold:
        status = REGIME_STATUS_WARN
    else:
        status = REGIME_STATUS_STABLE
    
    return status, distance


def update_regime_history(
    index: str,
    embedding: Dict[str, float],
    status: str,
    distance: float,
) -> None:
    """Update regime history with new entry and trim to configured window.
    
    Args:
        index: Index name
        embedding: Current embedding dictionary
        status: Current regime status
        distance: Distance from stable centroid
    """
    history = _safe_read_history(index)
    history_days = _get_env_int("G6_REGIME_EMBED_HISTORY_DAYS", _DEFAULT_HISTORY_DAYS)
    
    # Create new entry
    now = datetime.now(timezone.utc)
    entry = {
        "timestamp": now.isoformat(),
        "embedding": embedding,
        "status": status,
        "distance": distance,
    }
    
    # Append to history
    history.append(entry)
    
    # Trim to keep only last N days (keep at least 1 entry)
    if len(history) > max(1, history_days):
        history = history[-history_days:]
    
    # Write back atomically
    _safe_write_history(index, history)


def get_regime_summary(index: str) -> Dict[str, Any]:
    """Get a summary of regime history for given index.
    
    Returns:
        Dictionary with:
        - current: Current regime status info
        - recent_changes: List of recent status changes
        - avg_distance: Average distance over recent history
        - max_distance: Maximum distance in recent history
    """
    current = get_current_regime(index)
    history = _safe_read_history(index)
    
    if not history:
        return {
            "current": current,
            "recent_changes": [],
            "avg_distance": 0.0,
            "max_distance": 0.0,
        }
    
    # Find recent status changes
    recent_changes = []
    prev_status = None
    for entry in reversed(history[-10:]):  # Last 10 entries
        status = entry.get("status")
        if status != prev_status:
            recent_changes.append({
                "timestamp": entry.get("timestamp"),
                "status": status,
                "distance": entry.get("distance", 0.0),
            })
            prev_status = status
    
    # Compute statistics
    distances = [e.get("distance", 0.0) for e in history]
    avg_distance = sum(distances) / len(distances) if distances else 0.0
    max_distance = max(distances) if distances else 0.0
    
    return {
        "current": current,
        "recent_changes": recent_changes[:5],  # Top 5 most recent
        "avg_distance": round(avg_distance, 4),
        "max_distance": round(max_distance, 4),
    }
