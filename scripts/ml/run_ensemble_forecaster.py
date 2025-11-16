#!/usr/bin/env python3
"""
Ensemble Forecaster Serving Script

Run the ensemble path forecaster for real-time TP prediction.
Combines baseline, GBRT, and retrieval forecasters with adaptive weighting.

Usage:
    python scripts/ml/run_ensemble_forecaster.py \
        --config configs/ml/nifty_ensemble_config.json \
        --index NIFTY \
        --output data/ml/live_predictions/nifty_ensemble.csv \
        --interval 60

Features:
- Real-time forecasting with configurable update interval
- CSV output with timestamps and quantile predictions
- Prometheus metrics export (optional)
- Graceful error handling and fallbacks
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.path_forecast.ensemble import EnsembleForecaster, EnsembleConfig
from src.analytics.ml.baseline import baseline_tp


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
_LOG = logging.getLogger("run_ensemble_forecaster")


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load ensemble configuration from JSON file."""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        _LOG.error(f"Failed to load config from {config_path}: {e}")
        raise


def build_ensemble_config(config: Dict[str, Any]) -> EnsembleConfig:
    """Build EnsembleConfig from JSON configuration."""
    components = config.get("components", {})
    weighting = config.get("weighting", {})
    
    # Extract baseline config
    baseline_cfg = components.get("baseline", {})
    baseline_enabled = baseline_cfg.get("enabled", True)
    baseline_k = baseline_cfg.get("k_coefficient", 1.0)
    
    # Extract GBRT config
    gbrt_cfg = components.get("gbrt", {})
    gbrt_enabled = gbrt_cfg.get("enabled", True)
    gbrt_model_path = gbrt_cfg.get("model_path")
    if gbrt_model_path:
        gbrt_model_path = Path(gbrt_model_path)
    gbrt_feature_config = gbrt_cfg.get("feature_config", {})
    
    # Extract retrieval config
    retrieval_cfg = components.get("retrieval", {})
    retrieval_enabled = retrieval_cfg.get("enabled", True)
    retrieval_root = retrieval_cfg.get("data_root")
    if retrieval_root:
        retrieval_root = Path(retrieval_root)
    
    # Extract conformal config
    conformal_cfg = components.get("conformal", {})
    conformal_enabled = conformal_cfg.get("enabled", True)
    
    # Extract weighting config
    weights_high = weighting.get("weights_high_confidence", {})
    weights_low = weighting.get("weights_low_confidence", {})
    
    return EnsembleConfig(
        # Component enable flags
        baseline_enabled=baseline_enabled,
        gbrt_enabled=gbrt_enabled,
        retrieval_enabled=retrieval_enabled,
        conformal_enabled=conformal_enabled,
        # Baseline
        baseline_k=baseline_k,
        # GBRT
        gbrt_model_path=gbrt_model_path,
        gbrt_feature_config=gbrt_feature_config,
        # Retrieval
        retrieval_root=retrieval_root,
        retrieval_expiry_tag=retrieval_cfg.get("expiry_tag", "this_week"),
        retrieval_offset=retrieval_cfg.get("offset", "0"),
        retrieval_window=retrieval_cfg.get("window", 60),
        retrieval_k=retrieval_cfg.get("k", 20),
        retrieval_min_days=retrieval_cfg.get("min_days", 3),
        retrieval_distance_metric=retrieval_cfg.get("distance_metric", "l2"),
        retrieval_weight_mode=retrieval_cfg.get("weight_mode"),
        retrieval_use_ann=retrieval_cfg.get("use_ann", False),
        # Conformal
        conformal_target_coverage=conformal_cfg.get("target_coverage", 0.8),
        conformal_window=conformal_cfg.get("window", 600),
        conformal_min_radius=conformal_cfg.get("min_radius", 0.0),
        # Weighting
        weighting_strategy=weighting.get("strategy", "confidence_adaptive"),
        weights_high_conf_gbrt=weights_high.get("gbrt", 0.8),
        weights_high_conf_retrieval=weights_high.get("retrieval", 0.2),
        weights_low_conf_gbrt=weights_low.get("gbrt", 0.5),
        weights_low_conf_retrieval=weights_low.get("retrieval", 0.5),
        confidence_threshold=weighting.get("confidence_threshold", 0.7),
        min_candidates_threshold=weighting.get("min_candidates_threshold", 5),
        # Diagnostics
        enable_profiling=config.get("diagnostics", {}).get("enable_profiling", False),
    )


def generate_mock_context(index: str) -> Dict[str, Any]:
    """Generate mock context for testing.
    
    In production, this would come from live market data.
    """
    # Mock market data
    if index == "NIFTY":
        underlying = 19500.0
        avg_iv = 0.15
    elif index == "BANKNIFTY":
        underlying = 44000.0
        avg_iv = 0.18
    else:
        underlying = 10000.0
        avg_iv = 0.15
    
    return {
        "index": index,
        "now_ms": int(time.time() * 1000),
        "underlying": underlying,
        "avg_iv": avg_iv,
        "minutes_to_expiry": 300.0,  # 5 hours
        "live_rows": [],  # Empty for now
    }


def generate_mock_recent_window(n: int = 60) -> list:
    """Generate mock recent TP window for testing."""
    # Generate synthetic TP values around 100
    import random
    base_tp = 100.0
    window = []
    for i in range(n):
        # Add some variation
        tp = base_tp + random.gauss(0, 5)
        window.append([tp])
    return window


def run_forecaster(
    forecaster: EnsembleForecaster,
    index: str,
    output_path: Optional[Path],
    interval: int,
    max_iterations: Optional[int] = None,
) -> None:
    """Run forecaster in a loop with specified interval.
    
    Args:
        forecaster: Ensemble forecaster instance
        index: Index name (NIFTY/BANKNIFTY)
        output_path: Output CSV path (optional)
        interval: Update interval in seconds
        max_iterations: Maximum iterations (None = infinite)
    """
    iteration = 0
    
    # Prepare output file if specified
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Write header
        with open(output_path, 'w') as f:
            f.write("timestamp,index,horizon_min,p10,p50,p90,confidence,weight_gbrt,weight_retrieval\n")
    
    try:
        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            _LOG.info(f"Iteration {iteration}: Generating forecast for {index}")
            
            try:
                # Generate mock data (in production, fetch from live source)
                context = generate_mock_context(index)
                recent_window = generate_mock_recent_window()
                
                # Generate forecast
                t_start = time.time()
                times, quantiles = forecaster.forecast_path(
                    recent_window,
                    context=context,
                    quantiles=[0.1, 0.5, 0.9],
                    horizon_minutes=60,
                    bucket_ms=60000,
                )
                t_elapsed = time.time() - t_start
                
                # Extract metadata
                meta = forecaster.last_meta
                confidence = meta.get("confidence", 0.0)
                weight_gbrt = meta.get("weight_gbrt", 0.0)
                weight_retrieval = meta.get("weight_retrieval", 0.0)
                
                # Log forecast summary
                p10 = quantiles[0.1][0] if 0.1 in quantiles else 0.0
                p50 = quantiles[0.5][0] if 0.5 in quantiles else 0.0
                p90 = quantiles[0.9][0] if 0.9 in quantiles else 0.0
                
                _LOG.info(
                    f"Forecast: P10={p10:.2f}, P50={p50:.2f}, P90={p90:.2f} | "
                    f"Confidence={confidence:.3f} | Weights: GBRT={weight_gbrt:.2f}, "
                    f"Retrieval={weight_retrieval:.2f} | Time={t_elapsed:.3f}s"
                )
                
                # Write to output file
                if output_path:
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    with open(output_path, 'a') as f:
                        f.write(
                            f"{timestamp},{index},1,{p10:.4f},{p50:.4f},{p90:.4f},"
                            f"{confidence:.4f},{weight_gbrt:.4f},{weight_retrieval:.4f}\n"
                        )
                
            except Exception as e:
                _LOG.error(f"Forecast iteration failed: {e}", exc_info=True)
            
            # Wait for next interval
            if max_iterations is None or iteration < max_iterations:
                _LOG.debug(f"Sleeping for {interval} seconds...")
                time.sleep(interval)
    
    except KeyboardInterrupt:
        _LOG.info("Interrupted by user, shutting down...")
    except Exception as e:
        _LOG.error(f"Fatal error in forecaster loop: {e}", exc_info=True)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Run ensemble forecaster for real-time TP prediction"
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to ensemble configuration JSON file",
    )
    parser.add_argument(
        "--index",
        type=str,
        default="NIFTY",
        help="Index name (NIFTY, BANKNIFTY, etc.)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV file path (optional)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Update interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="Maximum number of iterations (default: infinite)",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run in daemon mode (infinite loop)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run in test mode (single iteration)",
    )
    
    args = parser.parse_args()
    
    # Load configuration
    _LOG.info(f"Loading configuration from {args.config}")
    config = load_config(args.config)
    ensemble_cfg = build_ensemble_config(config)
    
    # Initialize forecaster
    _LOG.info(f"Initializing ensemble forecaster for {args.index}")
    forecaster = EnsembleForecaster(ensemble_cfg)
    
    # Determine max iterations
    max_iterations = None
    if args.test:
        max_iterations = 1
    elif args.max_iterations:
        max_iterations = args.max_iterations
    
    # Run forecaster
    _LOG.info(f"Starting forecaster (interval={args.interval}s)")
    run_forecaster(
        forecaster,
        args.index,
        args.output,
        args.interval,
        max_iterations,
    )
    
    _LOG.info("Forecaster stopped")


if __name__ == "__main__":
    main()
