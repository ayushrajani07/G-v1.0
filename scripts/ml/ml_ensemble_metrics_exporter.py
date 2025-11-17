#!/usr/bin/env python3
"""
ML Ensemble Metrics Exporter - Phase 4 Implementation

Exports Prometheus metrics for:
- Ensemble forecast values (P10, P50, P90)
- Confidence scores
- Component weights
- Latency metrics
- Coverage and accuracy
- Model staleness

Part of Production Deployment (Phase 4) of ML ARM Implementation Roadmap.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

try:
    from prometheus_client import start_http_server, Gauge, Counter, Histogram
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

from src.path_forecast.ensemble import EnsembleForecaster, EnsembleConfig
from src.error_handling import safe_read_json

_LOG = logging.getLogger(__name__)


class MLEnsembleMetricsExporter:
    """Prometheus metrics exporter for ML Ensemble forecasting."""
    
    def __init__(self, index: str, config_path: Path, port: int = 9325):
        """
        Initialize metrics exporter.
        
        Args:
            index: Index name (NIFTY, BANKNIFTY)
            config_path: Path to ensemble configuration file
            port: Prometheus metrics port
        """
        self.index = index.upper()
        self.config_path = config_path
        self.port = port
        
        if not PROMETHEUS_AVAILABLE:
            raise ImportError("prometheus_client not installed. Install with: pip install prometheus-client")
        
        # Initialize Prometheus metrics
        self._init_metrics()
        
        # Load configuration and create forecaster
        self.config = self._load_config()
        self.forecaster = EnsembleForecaster(config=self.config, index=self.index)
        
        _LOG.info(f"Initialized metrics exporter for {self.index} on port {self.port}")
    
    def _init_metrics(self) -> None:
        """Initialize Prometheus metrics."""
        # Forecast quantile metrics
        self.forecast_p10 = Gauge(
            'g6_ml_ensemble_forecast_p10',
            'ML Ensemble forecast P10 quantile',
            ['index', 'horizon']
        )
        
        self.forecast_p50 = Gauge(
            'g6_ml_ensemble_forecast_p50',
            'ML Ensemble forecast P50 (median) quantile',
            ['index', 'horizon']
        )
        
        self.forecast_p90 = Gauge(
            'g6_ml_ensemble_forecast_p90',
            'ML Ensemble forecast P90 quantile',
            ['index', 'horizon']
        )
        
        # Confidence metrics
        self.confidence = Gauge(
            'g6_ml_ensemble_confidence',
            'ML Ensemble confidence score',
            ['index']
        )
        
        # Component weight metrics
        self.weight_gbrt = Gauge(
            'g6_ml_ensemble_weight_gbrt',
            'GBRT component weight in ensemble',
            ['index']
        )
        
        self.weight_retrieval = Gauge(
            'g6_ml_ensemble_weight_retrieval',
            'Retrieval component weight in ensemble',
            ['index']
        )
        
        # Latency metrics
        self.latency = Histogram(
            'g6_ml_ensemble_latency_seconds',
            'Forecast latency by component',
            ['index', 'component'],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
        )
        
        # Accuracy metrics (updated periodically)
        self.mae_p50 = Gauge(
            'g6_ml_ensemble_mae_p50',
            'Mean Absolute Error for P50 forecast',
            ['index']
        )
        
        self.coverage_actual = Gauge(
            'g6_ml_ensemble_coverage_actual',
            'Actual coverage rate (P10-P90 band)',
            ['index']
        )
        
        # Conformal band metrics
        self.conformal_radius = Gauge(
            'g6_ml_ensemble_conformal_radius',
            'Conformal prediction band radius',
            ['index']
        )
        
        # Model staleness
        self.model_age_days = Gauge(
            'g6_ml_ensemble_model_age_days',
            'Age of GBRT model in days',
            ['index']
        )
        
        # Error counters
        self.forecast_errors = Counter(
            'g6_ml_ensemble_forecast_errors_total',
            'Total forecast errors',
            ['index', 'error_type']
        )
        
        # Forecast counter
        self.forecast_count = Counter(
            'g6_ml_ensemble_forecasts_total',
            'Total forecasts generated',
            ['index']
        )
    
    def _load_config(self) -> EnsembleConfig:
        """Load ensemble configuration."""
        config_data = safe_read_json(self.config_path)
        if config_data is None:
            raise ValueError(f"Failed to load config from {self.config_path}")
        
        components = config_data.get('components', {})
        weighting = config_data.get('weighting', {})
        
        config = EnsembleConfig(
            baseline_enabled=components.get('baseline', {}).get('enabled', True),
            gbrt_enabled=components.get('gbrt', {}).get('enabled', True),
            retrieval_enabled=components.get('retrieval', {}).get('enabled', True),
            conformal_enabled=components.get('conformal', {}).get('enabled', True),
            baseline_k=components.get('baseline', {}).get('k_coefficient', 1.0),
            gbrt_model_path=Path(components.get('gbrt', {}).get('model_path', 'models/gbrt/')),
            retrieval_k=components.get('retrieval', {}).get('k', 20),
            retrieval_window=components.get('retrieval', {}).get('window', 60),
            conformal_target_coverage=components.get('conformal', {}).get('target_coverage', 0.8),
            weighting_strategy=weighting.get('strategy', 'confidence_adaptive'),
            confidence_threshold=weighting.get('confidence_threshold', 0.7),
            weights_high_conf_gbrt=weighting.get('weights_high_confidence', {}).get('gbrt', 0.8),
            weights_high_conf_retrieval=weighting.get('weights_high_confidence', {}).get('retrieval', 0.2),
            weights_low_conf_gbrt=weighting.get('weights_low_confidence', {}).get('gbrt', 0.5),
            weights_low_conf_retrieval=weighting.get('weights_low_confidence', {}).get('retrieval', 0.5)
        )
        
        return config
    
    def export_forecast_metrics(self, horizon: int = 60) -> None:
        """
        Generate and export forecast metrics.
        
        Args:
            horizon: Forecast horizon in minutes
        """
        try:
            start_time = time.time()
            
            # Generate mock forecast (in production, would use live data)
            # This is a placeholder - real implementation would call forecaster.forecast_path()
            forecast_data = {
                'p10': 180.5,
                'p50': 195.3,
                'p90': 210.8,
                'confidence': 0.75,
                'weights': {'gbrt': 0.7, 'retrieval': 0.3},
                'conformal_radius': 15.2
            }
            
            # Update forecast metrics
            self.forecast_p10.labels(index=self.index, horizon=horizon).set(forecast_data['p10'])
            self.forecast_p50.labels(index=self.index, horizon=horizon).set(forecast_data['p50'])
            self.forecast_p90.labels(index=self.index, horizon=horizon).set(forecast_data['p90'])
            
            # Update confidence
            self.confidence.labels(index=self.index).set(forecast_data['confidence'])
            
            # Update weights
            self.weight_gbrt.labels(index=self.index).set(forecast_data['weights']['gbrt'])
            self.weight_retrieval.labels(index=self.index).set(forecast_data['weights']['retrieval'])
            
            # Update conformal radius
            self.conformal_radius.labels(index=self.index).set(forecast_data['conformal_radius'])
            
            # Record latency
            latency = time.time() - start_time
            self.latency.labels(index=self.index, component='total').observe(latency)
            
            # Increment forecast counter
            self.forecast_count.labels(index=self.index).inc()
            
            _LOG.debug(f"Exported forecast metrics for {self.index} (latency: {latency:.3f}s)")
            
        except Exception as e:
            _LOG.error(f"Error exporting forecast metrics: {e}", exc_info=True)
            self.forecast_errors.labels(index=self.index, error_type='forecast').inc()
    
    def export_accuracy_metrics(self, mae: float, coverage: float) -> None:
        """
        Export accuracy metrics.
        
        Args:
            mae: Mean Absolute Error for P50
            coverage: Actual coverage rate
        """
        try:
            self.mae_p50.labels(index=self.index).set(mae)
            self.coverage_actual.labels(index=self.index).set(coverage)
            _LOG.debug(f"Updated accuracy metrics: MAE={mae:.2f}, Coverage={coverage:.2%}")
        except Exception as e:
            _LOG.error(f"Error exporting accuracy metrics: {e}", exc_info=True)
    
    def export_model_age(self, age_days: float) -> None:
        """
        Export model age metric.
        
        Args:
            age_days: Model age in days
        """
        try:
            self.model_age_days.labels(index=self.index).set(age_days)
            _LOG.debug(f"Updated model age: {age_days:.1f} days")
        except Exception as e:
            _LOG.error(f"Error exporting model age: {e}", exc_info=True)
    
    def run(self, interval: int = 60) -> None:
        """
        Run metrics exporter continuously.
        
        Args:
            interval: Export interval in seconds
        """
        # Start Prometheus HTTP server
        start_http_server(self.port)
        _LOG.info(f"Prometheus metrics server started on port {self.port}")
        _LOG.info(f"Metrics available at http://localhost:{self.port}/metrics")
        
        # Export initial model age
        self.export_model_age(3.5)  # Mock value
        
        # Main export loop
        _LOG.info(f"Starting continuous export with {interval}s interval")
        try:
            while True:
                self.export_forecast_metrics()
                
                # Periodically update accuracy metrics (every 10 cycles)
                if self.forecast_count._value.get() % 10 == 0:
                    # Mock values - in production, would compute from actual vs predicted
                    self.export_accuracy_metrics(mae=9.2, coverage=0.82)
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            _LOG.info("Metrics exporter stopped by user")
        except Exception as e:
            _LOG.error(f"Fatal error in metrics exporter: {e}", exc_info=True)
            raise


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='ML Ensemble Metrics Exporter for Prometheus'
    )
    parser.add_argument(
        '--index',
        required=True,
        choices=['NIFTY', 'BANKNIFTY'],
        help='Index name'
    )
    parser.add_argument(
        '--config',
        type=Path,
        help='Path to ensemble config file'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=9325,
        help='Prometheus metrics port (default: 9325)'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=60,
        help='Export interval in seconds (default: 60)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    
    args = parser.parse_args()
    
    # Phase 3: Use simplified logging setup
    from src.utils.logging_utils import setup_logging
    log_level = 'DEBUG' if args.debug else 'INFO'
    setup_logging(terminal_level=log_level)
    
    # Determine config path
    if args.config:
        config_path = args.config
    else:
        # Default config location
        config_path = Path(__file__).resolve().parents[2] / 'configs' / 'ml' / f'{args.index.lower()}_ensemble_config.json'
    
    if not config_path.exists():
        _LOG.error(f"Config file not found: {config_path}")
        return
    
    # Create and run exporter
    try:
        exporter = MLEnsembleMetricsExporter(
            index=args.index,
            config_path=config_path,
            port=args.port
        )
        exporter.run(interval=args.interval)
    except Exception as e:
        _LOG.error(f"Failed to start exporter: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()
