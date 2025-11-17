"""Unit tests for Phase 9 modular config structures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.path_forecast.config_structs import (
    RetrievalConfig,
    PruningConfig,
    RegimeConfig,
    AnnConfig,
)


class TestPruningConfig:
    """Test PruningConfig."""
    
    def test_default_values(self):
        """Test default values are set correctly."""
        cfg = PruningConfig()
        assert cfg.min_days == 3
        assert cfg.min_future == 30
        assert cfg.max_days_scan is None
        assert cfg.min_hist_rows is None
        assert cfg.max_time_gap_ratio is None
    
    def test_custom_values(self):
        """Test custom values are preserved."""
        cfg = PruningConfig(
            min_days=5,
            min_future=60,
            max_days_scan=100,
            min_hist_rows=200,
            max_time_gap_ratio=0.3
        )
        assert cfg.min_days == 5
        assert cfg.min_future == 60
        assert cfg.max_days_scan == 100
        assert cfg.min_hist_rows == 200
        assert cfg.max_time_gap_ratio == 0.3


class TestRegimeConfig:
    """Test RegimeConfig."""
    
    def test_default_values(self):
        """Test default values are set correctly."""
        cfg = RegimeConfig()
        assert cfg.distance_metric == "l2"
        assert cfg.recent_gamma == 0.9
        assert cfg.weight_mode is None
        assert cfg.regime_tolerance is None
        assert cfg.regime_penalty == 1.25
    
    def test_custom_distance_metric(self):
        """Test custom distance metric."""
        cfg = RegimeConfig(distance_metric="cosine")
        assert cfg.distance_metric == "cosine"
    
    def test_recent_l2_with_gamma(self):
        """Test recent_l2 mode with custom gamma."""
        cfg = RegimeConfig(
            distance_metric="recent_l2",
            recent_gamma=0.95
        )
        assert cfg.distance_metric == "recent_l2"
        assert cfg.recent_gamma == 0.95


class TestAnnConfig:
    """Test AnnConfig."""
    
    def test_default_values(self):
        """Test default values are set correctly."""
        cfg = AnnConfig()
        assert cfg.use_ann is False
        assert cfg.ann_space == "cosine"
        assert cfg.ann_max_candidates is None
        assert cfg.ann_dim is None
    
    def test_ann_enabled(self):
        """Test ANN enabled configuration."""
        cfg = AnnConfig(
            use_ann=True,
            ann_space="l2",
            ann_max_candidates=50,
            ann_dim=60
        )
        assert cfg.use_ann is True
        assert cfg.ann_space == "l2"
        assert cfg.ann_max_candidates == 50
        assert cfg.ann_dim == 60


class TestRetrievalConfig:
    """Test RetrievalConfig backward compatibility and modular features."""
    
    def test_legacy_flat_construction(self):
        """Test legacy flat construction still works."""
        cfg = RetrievalConfig(
            root=Path("/data"),
            expiry_tag="this_week",
            offset="0",
            window=60,
            k=15,
            min_days=5,
            min_future=30,
            distance_metric="cosine",
            use_ann=True,
            ann_space="l2"
        )
        
        # Verify flat fields
        assert cfg.window == 60
        assert cfg.k == 15
        assert cfg.min_days == 5
        assert cfg.distance_metric == "cosine"
        assert cfg.use_ann is True
        
        # Verify modular configs auto-populated
        assert cfg.pruning is not None
        assert cfg.pruning.min_days == 5
        assert cfg.pruning.min_future == 30
        
        assert cfg.regime is not None
        assert cfg.regime.distance_metric == "cosine"
        
        assert cfg.ann is not None
        assert cfg.ann.use_ann is True
        assert cfg.ann.ann_space == "l2"
    
    def test_modular_construction(self):
        """Test new modular construction via from_modular."""
        pruning = PruningConfig(min_days=7, min_future=60)
        regime = RegimeConfig(distance_metric="recent_l2", recent_gamma=0.95)
        ann = AnnConfig(use_ann=True, ann_max_candidates=100)
        
        cfg = RetrievalConfig.from_modular(
            root=Path("/data"),
            expiry_tag="this_week",
            window=90,
            k=20,
            pruning=pruning,
            regime=regime,
            ann=ann
        )
        
        assert cfg.window == 90
        assert cfg.k == 20
        assert cfg.pruning.min_days == 7
        assert cfg.regime.distance_metric == "recent_l2"
        assert cfg.ann.use_ann is True
        assert cfg.ann.ann_max_candidates == 100
    
    def test_legacy_dict_conversion(self):
        """Test conversion to legacy dict format."""
        cfg = RetrievalConfig(
            root=Path("/data"),
            window=60,
            k=15,
            min_days=5,
            distance_metric="cosine",
            use_ann=True
        )
        
        legacy = cfg.legacy_dict()
        
        assert legacy['window'] == 60
        assert legacy['k'] == 15
        assert legacy['min_days'] == 5
        assert legacy['distance_metric'] == "cosine"
        assert legacy['use_ann'] is True
        assert 'expiry_tag' in legacy
        assert 'offset' in legacy
    
    def test_modular_override_legacy(self):
        """Test that modular configs override legacy flat values."""
        # Set both flat and modular values
        pruning = PruningConfig(min_days=10)
        cfg = RetrievalConfig(
            root=Path("/data"),
            min_days=5,  # Legacy value
            pruning=pruning  # Modular override
        )
        
        # Modular value should be used
        assert cfg.pruning.min_days == 10
        
        # Legacy dict should reflect modular value
        legacy = cfg.legacy_dict()
        assert legacy['min_days'] == 10
    
    def test_extras_field(self):
        """Test extras field for forward compatibility."""
        cfg = RetrievalConfig.from_modular(
            root=Path("/data"),
            custom_param="custom_value",
            another_param=42
        )
        
        assert cfg.extras['custom_param'] == "custom_value"
        assert cfg.extras['another_param'] == 42
    
    def test_post_init_creates_sub_configs(self):
        """Test that __post_init__ creates sub-configs from flat values."""
        cfg = RetrievalConfig(
            root=Path("/data"),
            min_days=7,
            distance_metric="recent_l2",
            use_ann=True
        )
        
        # Sub-configs should be auto-created
        assert cfg.pruning is not None
        assert cfg.pruning.min_days == 7
        
        assert cfg.regime is not None
        assert cfg.regime.distance_metric == "recent_l2"
        
        assert cfg.ann is not None
        assert cfg.ann.use_ann is True


class TestConfigSerialization:
    """Test config serialization for compatibility."""
    
    def test_pruning_config_dict(self):
        """Test PruningConfig can be converted to dict."""
        cfg = PruningConfig(min_days=5, max_days_scan=100)
        d = {
            'min_days': cfg.min_days,
            'min_future': cfg.min_future,
            'max_days_scan': cfg.max_days_scan,
            'min_hist_rows': cfg.min_hist_rows,
            'max_time_gap_ratio': cfg.max_time_gap_ratio,
        }
        
        # Should be JSON-serializable
        json_str = json.dumps(d)
        assert json_str is not None
        
        # Should round-trip
        parsed = json.loads(json_str)
        assert parsed['min_days'] == 5
        assert parsed['max_days_scan'] == 100
    
    def test_full_config_legacy_dict_serializable(self):
        """Test that legacy_dict is JSON-serializable."""
        cfg = RetrievalConfig(
            root=Path("/data"),
            window=60,
            k=15,
            use_ann=True
        )
        
        legacy = cfg.legacy_dict()
        
        # Should be JSON-serializable
        json_str = json.dumps(legacy)
        assert json_str is not None
        
        # Should round-trip
        parsed = json.loads(json_str)
        assert parsed['window'] == 60
        assert parsed['k'] == 15
        assert parsed['use_ann'] is True
