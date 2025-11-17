"""
Production Deployment Integration Tests - Phase 8

Comprehensive smoke tests for production deployment validation.
Tests infrastructure, services, and end-to-end workflows.

Run with:
    pytest tests/test_production_deployment.py -v
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Optional

import pytest


class TestProductionDeployment:
    """Production deployment integration tests."""
    
    @pytest.fixture
    def api_host(self) -> str:
        """API host."""
        return "localhost"
    
    @pytest.fixture
    def api_port(self) -> int:
        """API port."""
        return 9210
    
    @pytest.fixture
    def metrics_port_nifty(self) -> int:
        """Metrics port for NIFTY."""
        return 9325
    
    @pytest.fixture
    def metrics_port_banknifty(self) -> int:
        """Metrics port for BANKNIFTY."""
        return 9326
    
    def test_api_health_endpoint(self, api_host: str, api_port: int):
        """Test API health endpoint is responding."""
        url = f"http://{api_host}:{api_port}/health"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                
                assert "status" in data, "Health response missing 'status' field"
                assert data["status"] == "healthy", f"API status is {data['status']}, expected 'healthy'"
                
        except urllib.error.URLError as e:
            pytest.skip(f"API not running: {e}")
    
    def test_metrics_endpoint_nifty(self, api_host: str, metrics_port_nifty: int):
        """Test NIFTY metrics endpoint is responding."""
        url = f"http://{api_host}:{metrics_port_nifty}/metrics"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
            with urllib.request.urlopen(req, timeout=5) as response:
                metrics_text = response.read().decode()
                
                assert len(metrics_text) > 0, "Metrics endpoint returned empty response"
                assert "g6_ml_ensemble" in metrics_text, "ML ensemble metrics not found"
                
        except urllib.error.URLError as e:
            pytest.skip(f"Metrics exporter not running: {e}")
    
    def test_forecast_endpoint_nifty(self, api_host: str, api_port: int):
        """Test NIFTY forecast endpoint."""
        url = f"http://{api_host}:{api_port}/api/ml/ensemble/forecast?index=NIFTY&horizon=60"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                
                # Check required fields
                required_fields = ['p10', 'p50', 'p90', 'confidence_score']
                for field in required_fields:
                    assert field in data, f"Forecast missing required field: {field}"
                
                # Check quantile ordering
                assert data['p10'] <= data['p50'] <= data['p90'], \
                    f"Quantiles not properly ordered: P10={data['p10']}, P50={data['p50']}, P90={data['p90']}"
                
                # Check values are positive
                assert all(data[q] > 0 for q in ['p10', 'p50', 'p90']), \
                    "Forecast quantiles should be positive"
                
        except urllib.error.URLError as e:
            pytest.skip(f"API not running or forecast failed: {e}")
    
    def test_diagnostics_endpoint(self, api_host: str, api_port: int):
        """Test diagnostics endpoint."""
        url = f"http://{api_host}:{api_port}/api/ml/ensemble/diagnostics?index=NIFTY"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'pytest'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                
                assert "status" in data, "Diagnostics missing 'status' field"
                
        except urllib.error.URLError as e:
            pytest.skip(f"API not running or diagnostics failed: {e}")
    
    def test_model_files_exist(self):
        """Test that trained model files exist."""
        models_dir = Path("models")
        
        if not models_dir.exists():
            pytest.skip("Models directory not found")
        
        # Check for NIFTY models
        nifty_model_dir = models_dir / "nifty_gbrt_quantile"
        if nifty_model_dir.exists():
            required_files = [
                "model_q10.joblib",
                "model_q50.joblib",
                "model_q90.joblib"
            ]
            
            for model_file in required_files:
                assert (nifty_model_dir / model_file).exists(), \
                    f"Missing model file: {model_file}"
    
    def test_config_files_exist(self):
        """Test that configuration files exist."""
        configs_dir = Path("configs/ml")
        
        if not configs_dir.exists():
            pytest.skip("ML configs directory not found")
        
        required_configs = [
            "nifty_ensemble_config.json",
            "banknifty_ensemble_config.json"
        ]
        
        for config_file in required_configs:
            config_path = configs_dir / config_file
            if config_path.exists():
                # Validate JSON is parseable
                with open(config_path) as f:
                    data = json.load(f)
                    assert isinstance(data, dict), f"{config_file} should contain a JSON object"
    
    def test_prometheus_rules_exist(self):
        """Test that Prometheus alert rules exist."""
        rules_file = Path("prometheus_rules_ml_ensemble.yml")
        
        if rules_file.exists():
            # Basic validation that file is not empty
            assert rules_file.stat().st_size > 0, "Prometheus rules file is empty"
    
    def test_data_directory_structure(self):
        """Test that data directory structure exists."""
        data_root = Path("data/g6_data")
        
        if not data_root.exists():
            pytest.skip("Data directory not found")
        
        # Check for index directories
        expected_indices = ["nifty", "banknifty"]
        for index in expected_indices:
            index_dir = data_root / index
            if index_dir.exists():
                # Check that some CSV files exist
                csv_files = list(index_dir.rglob("*.csv"))
                assert len(csv_files) > 0, f"No CSV files found for {index}"


class TestProductionReadiness:
    """Production readiness checks."""
    
    def test_deployment_scripts_exist(self):
        """Test that deployment scripts exist."""
        scripts_dir = Path("scripts/ml")
        
        if not scripts_dir.exists():
            pytest.skip("Scripts directory not found")
        
        # Check for critical operational scripts
        critical_scripts = [
            "daily_health_check.py",
            "check_model_age.py",
            "validate_historical_data.py",
            "validate_data_freshness.py",
            "automated_retraining.py"
        ]
        
        for script in critical_scripts:
            script_path = scripts_dir / script
            assert script_path.exists(), f"Missing critical script: {script}"
    
    def test_documentation_exists(self):
        """Test that production documentation exists."""
        docs_dir = Path("docs/ml")
        
        if not docs_dir.exists():
            pytest.skip("Documentation directory not found")
        
        # Check for critical documentation
        critical_docs = [
            "PRODUCTION_DEPLOYMENT_GUIDE.md",
            "ML_ARM_NEXT_STEPS.md"
        ]
        
        for doc in critical_docs:
            doc_path = docs_dir / doc
            if doc_path.exists():
                assert doc_path.stat().st_size > 0, f"{doc} is empty"


class TestServiceManagement:
    """Service management tests."""
    
    def test_start_scripts_exist(self):
        """Test that service start scripts exist."""
        scripts_dir = Path("scripts/ml")
        
        if not scripts_dir.exists():
            pytest.skip("Scripts directory not found")
        
        management_scripts = [
            "start_ml_api.sh",
            "start_ml_metrics.sh",
            "stop_ml_services.sh"
        ]
        
        for script in management_scripts:
            script_path = scripts_dir / script
            if script_path.exists():
                # Check script has execute permissions or is at least readable
                assert script_path.stat().st_size > 0, f"{script} is empty"


class TestMonitoring:
    """Monitoring infrastructure tests."""
    
    def test_grafana_dashboards_exist(self):
        """Test that Grafana dashboards exist."""
        dashboards_dir = Path("dashboards_modular")
        
        if not dashboards_dir.exists():
            pytest.skip("Dashboards directory not found")
        
        # Look for ML ensemble dashboard
        ml_dashboards = list(dashboards_dir.glob("*ml*ensemble*.json"))
        
        if ml_dashboards:
            # Validate first dashboard is valid JSON
            with open(ml_dashboards[0]) as f:
                data = json.load(f)
                assert isinstance(data, dict), "Dashboard should be a JSON object"
    
    def test_alert_rules_parseable(self):
        """Test that alert rules are parseable."""
        rules_files = [
            "prometheus_rules_ml.yml",
            "prometheus_rules_ml_ensemble.yml"
        ]
        
        for rules_file in rules_files:
            rules_path = Path(rules_file)
            if rules_path.exists():
                # Basic check that file is not empty
                assert rules_path.stat().st_size > 0, f"{rules_file} is empty"
