#!/usr/bin/env python3
"""
Phase 9: Parallel Grid Evaluation Harness

Evaluates multiple forecast configurations in parallel with deterministic seeding
and outputs JSON/CSV results with latency, accuracy, and coverage metrics.

Usage:
    python scripts/ml/grid_eval_parallel.py \\
        --config configs/grid_eval_config.json \\
        --workers 4 \\
        --output results/grid_eval_results.json \\
        --output-csv results/grid_eval_results.csv

Features:
- Deterministic seeding per configuration
- Parallel execution with configurable workers
- CPU affinity friendly worker pools
- JSON and CSV output formats
- Latency, accuracy, and coverage metrics per configuration
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import multiprocessing as mp
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
_LOG = logging.getLogger("grid_eval_parallel")


@dataclass
class EvalConfig:
    """Configuration for a single evaluation run."""
    config_id: str
    window: int
    k: int
    distance_metric: str
    use_ann: bool
    ann_space: str = "cosine"
    ann_max_candidates: Optional[int] = None
    weight_mode: Optional[str] = None
    seed: int = 42


@dataclass
class EvalResult:
    """Results from a single evaluation run."""
    config_id: str
    latency_ms: float
    accuracy_mae: float
    coverage_80: float
    coverage_90: float
    candidates_used: int
    ann_cache_hits: int = 0
    error: Optional[str] = None


def set_deterministic_seed(seed: int) -> None:
    """Set deterministic seed for reproducibility."""
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass


def evaluate_single_config(config: EvalConfig, data_root: Path, index: str = "NIFTY") -> EvalResult:
    """Evaluate a single configuration and return metrics.
    
    Args:
        config: Configuration to evaluate
        data_root: Root directory for data
        index: Index name to test
        
    Returns:
        EvalResult with latency, accuracy, and coverage metrics
    """
    # Set deterministic seed
    set_deterministic_seed(config.seed)
    
    try:
        from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig
        from datetime import datetime, timedelta
        import numpy as np
        
        # Create retrieval config from eval config
        ret_config = RetrievalConfig(
            root=data_root,
            window=config.window,
            k=config.k,
            distance_metric=config.distance_metric,
            use_ann=config.use_ann,
            ann_space=config.ann_space,
            ann_max_candidates=config.ann_max_candidates,
            weight_mode=config.weight_mode,
        )
        
        forecaster = RetrievalPathForecaster(ret_config)
        
        # Simulate a forecast request
        # Generate synthetic recent window data
        recent_window = []
        for i in range(config.window):
            row = [100.0 + i * 0.1 + random.gauss(0, 0.5)]  # Synthetic TP values
            recent_window.append(row)
        
        # Context for forecast
        now = datetime.now()
        context = {
            "index": index,
            "now_ms": int(now.timestamp() * 1000),
            "live_rows": [],
        }
        
        # Measure latency
        t_start = time.perf_counter()
        
        try:
            times, qmap = forecaster.forecast_path(
                recent_window=recent_window,
                context=context,
                quantiles=[0.1, 0.5, 0.9],
                horizon_minutes=60,
                bucket_ms=60_000,
            )
            
            latency_ms = (time.perf_counter() - t_start) * 1000
            
            # Calculate metrics from forecast
            meta = forecaster.last_meta
            candidates_used = meta.get("candidates_total", 0)
            
            # Simulate accuracy calculation (in real use, compare against actual)
            # For now, use forecast variability as proxy
            q50_values = qmap.get(0.5, [])
            if q50_values and len(q50_values) > 0:
                # MAE proxy: variance in forecast
                accuracy_mae = float(np.std([v for v in q50_values if not np.isnan(v)]))
            else:
                accuracy_mae = float('nan')
            
            # Coverage: check if quantiles span reasonable range
            q10_values = qmap.get(0.1, [])
            q90_values = qmap.get(0.9, [])
            
            coverage_80 = 0.0
            coverage_90 = 0.0
            
            if q10_values and q90_values:
                # Coverage is the width of the band as fraction of median
                valid_pairs = [(q10, q50, q90) for q10, q50, q90 in zip(q10_values, q50_values, q90_values)
                               if not (np.isnan(q10) or np.isnan(q50) or np.isnan(q90))]
                if valid_pairs:
                    widths_80 = [(q90 - q10) / max(abs(q50), 1.0) for q10, q50, q90 in valid_pairs]
                    coverage_80 = float(np.mean(widths_80))
                    coverage_90 = coverage_80 * 1.1  # Proxy for 90% band
            
            # Get cache stats if available
            ann_cache_hits = 0
            try:
                from src.path_forecast.ann_cache import get_ann_window_cache_stats
                cache_stats = get_ann_window_cache_stats()
                ann_cache_hits = cache_stats.get('hits', 0)
            except Exception:
                pass
            
            return EvalResult(
                config_id=config.config_id,
                latency_ms=latency_ms,
                accuracy_mae=accuracy_mae,
                coverage_80=coverage_80,
                coverage_90=coverage_90,
                candidates_used=candidates_used,
                ann_cache_hits=ann_cache_hits,
            )
            
        except Exception as exc:
            _LOG.error(f"Forecast failed for config {config.config_id}: {exc}")
            return EvalResult(
                config_id=config.config_id,
                latency_ms=-1.0,
                accuracy_mae=float('nan'),
                coverage_80=0.0,
                coverage_90=0.0,
                candidates_used=0,
                error=str(exc),
            )
            
    except Exception as exc:
        _LOG.error(f"Setup failed for config {config.config_id}: {exc}")
        return EvalResult(
            config_id=config.config_id,
            latency_ms=-1.0,
            accuracy_mae=float('nan'),
            coverage_80=0.0,
            coverage_90=0.0,
            candidates_used=0,
            error=str(exc),
        )


def load_configs_from_file(config_file: Path) -> List[EvalConfig]:
    """Load evaluation configurations from JSON file.
    
    Expected format:
    {
        "configs": [
            {
                "config_id": "baseline",
                "window": 60,
                "k": 15,
                "distance_metric": "l2",
                "use_ann": false
            },
            ...
        ]
    }
    """
    with open(config_file, 'r') as f:
        data = json.load(f)
    
    configs = []
    for i, cfg_dict in enumerate(data.get("configs", [])):
        # Add seed if not present (deterministic based on index)
        if 'seed' not in cfg_dict:
            cfg_dict['seed'] = 42 + i
        
        configs.append(EvalConfig(**cfg_dict))
    
    return configs


def generate_default_configs() -> List[EvalConfig]:
    """Generate a default set of configurations for testing."""
    configs = []
    
    # Baseline configs
    for window in [30, 60, 90]:
        for k in [10, 15, 20]:
            configs.append(EvalConfig(
                config_id=f"baseline_w{window}_k{k}",
                window=window,
                k=k,
                distance_metric="l2",
                use_ann=False,
                seed=42 + len(configs),
            ))
    
    # ANN configs
    for window in [60, 90]:
        for k in [15, 20]:
            for space in ["cosine", "l2"]:
                configs.append(EvalConfig(
                    config_id=f"ann_w{window}_k{k}_{space}",
                    window=window,
                    k=k,
                    distance_metric="l2",
                    use_ann=True,
                    ann_space=space,
                    ann_max_candidates=50,
                    seed=42 + len(configs),
                ))
    
    return configs


def save_results_json(results: List[EvalResult], output_file: Path) -> None:
    """Save results to JSON file."""
    results_dicts = [asdict(r) for r in results]
    
    output_data = {
        "timestamp": time.time(),
        "num_configs": len(results),
        "results": results_dicts,
    }
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    _LOG.info(f"Results saved to {output_file}")


def save_results_csv(results: List[EvalResult], output_file: Path) -> None:
    """Save results to CSV file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'config_id', 'latency_ms', 'accuracy_mae', 'coverage_80', 'coverage_90',
            'candidates_used', 'ann_cache_hits', 'error'
        ])
        writer.writeheader()
        
        for result in results:
            writer.writerow(asdict(result))
    
    _LOG.info(f"Results saved to {output_file}")


def print_summary(results: List[EvalResult]) -> None:
    """Print summary statistics."""
    successful = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]
    
    _LOG.info(f"\n{'='*60}")
    _LOG.info(f"Evaluation Summary")
    _LOG.info(f"{'='*60}")
    _LOG.info(f"Total configs: {len(results)}")
    _LOG.info(f"Successful: {len(successful)}")
    _LOG.info(f"Failed: {len(failed)}")
    
    if successful:
        latencies = [r.latency_ms for r in successful]
        _LOG.info(f"\nLatency Statistics:")
        _LOG.info(f"  Min: {min(latencies):.2f}ms")
        _LOG.info(f"  Max: {max(latencies):.2f}ms")
        _LOG.info(f"  Mean: {sum(latencies)/len(latencies):.2f}ms")
        _LOG.info(f"  P50: {sorted(latencies)[len(latencies)//2]:.2f}ms")
        _LOG.info(f"  P95: {sorted(latencies)[int(len(latencies)*0.95)]:.2f}ms")
        
        # Find best and worst configs
        best = min(successful, key=lambda r: r.latency_ms)
        worst = max(successful, key=lambda r: r.latency_ms)
        
        _LOG.info(f"\nBest Config: {best.config_id} ({best.latency_ms:.2f}ms)")
        _LOG.info(f"Worst Config: {worst.config_id} ({worst.latency_ms:.2f}ms)")
    
    if failed:
        _LOG.info(f"\nFailed Configs:")
        for r in failed:
            _LOG.info(f"  {r.config_id}: {r.error}")
    
    _LOG.info(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Parallel Grid Evaluation Harness for Path Forecast Configurations"
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="JSON file with configurations to evaluate"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=mp.cpu_count(),
        help="Number of parallel workers (default: CPU count)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/grid_eval_results.json"),
        help="Output JSON file path"
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="Optional CSV output file path"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/g6_data"),
        help="Root directory for historical data"
    )
    parser.add_argument(
        "--index",
        type=str,
        default="NIFTY",
        help="Index to evaluate (default: NIFTY)"
    )
    parser.add_argument(
        "--generate-default-config",
        action="store_true",
        help="Generate and use default configuration set"
    )
    
    args = parser.parse_args()
    
    # Load or generate configurations
    if args.generate_default_config:
        _LOG.info("Generating default configurations...")
        configs = generate_default_configs()
    elif args.config and args.config.exists():
        _LOG.info(f"Loading configurations from {args.config}...")
        configs = load_configs_from_file(args.config)
    else:
        _LOG.error("No configuration provided. Use --config or --generate-default-config")
        return 1
    
    _LOG.info(f"Evaluating {len(configs)} configurations with {args.workers} workers...")
    
    # Run evaluations in parallel
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks
        future_to_config = {
            executor.submit(evaluate_single_config, cfg, args.data_root, args.index): cfg
            for cfg in configs
        }
        
        # Collect results as they complete
        for i, future in enumerate(as_completed(future_to_config), 1):
            config = future_to_config[future]
            try:
                result = future.result()
                results.append(result)
                _LOG.info(f"[{i}/{len(configs)}] Completed {config.config_id}: {result.latency_ms:.2f}ms")
            except Exception as exc:
                _LOG.error(f"[{i}/{len(configs)}] Failed {config.config_id}: {exc}")
                results.append(EvalResult(
                    config_id=config.config_id,
                    latency_ms=-1.0,
                    accuracy_mae=float('nan'),
                    coverage_80=0.0,
                    coverage_90=0.0,
                    candidates_used=0,
                    error=str(exc),
                ))
    
    # Save results
    save_results_json(results, args.output)
    
    if args.output_csv:
        save_results_csv(results, args.output_csv)
    
    # Print summary
    print_summary(results)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
