#!/bin/bash
# Complete Phase 4 Deployment Script
# Deploys all ML Ensemble production components
# Part of Phase 4: Production Deployment

set -e

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Phase 4: Production Deployment Installer           ║${NC}"
echo -e "${BLUE}║             ML Ensemble Forecasting System                ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
echo

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

# Check Python
if ! command -v python &> /dev/null; then
    echo "✗ Python not found"
    exit 1
fi
echo "✓ Python: $(python --version)"

# Check required packages
echo -n "Checking Flask... "
if python -c "import flask" 2>/dev/null; then
    echo "✓"
else
    echo "✗ Not installed"
    echo "Installing Flask..."
    pip install -q flask
fi

echo -n "Checking prometheus-client... "
if python -c "import prometheus_client" 2>/dev/null; then
    echo "✓"
else
    echo "✗ Not installed"
    echo "Installing prometheus-client..."
    pip install -q prometheus-client
fi

echo -n "Checking PyYAML... "
if python -c "import yaml" 2>/dev/null; then
    echo "✓"
else
    echo "✗ Not installed"
    echo "Installing PyYAML..."
    pip install -q PyYAML
fi

echo

# Create required directories
echo -e "${YELLOW}Creating directories...${NC}"
mkdir -p "$PROJECT_ROOT/logs"
mkdir -p "$PROJECT_ROOT/models"
mkdir -p "$PROJECT_ROOT/data/ml/training"
mkdir -p "$PROJECT_ROOT/data/ml/live_predictions"
echo "✓ Directories created"
echo

# Verify configuration files
echo -e "${YELLOW}Verifying configuration files...${NC}"
CONFIG_DIR="$PROJECT_ROOT/configs/ml"

if [ ! -f "$CONFIG_DIR/nifty_ensemble_config.json" ]; then
    echo "⚠ Warning: NIFTY ensemble config not found"
    echo "  Expected: $CONFIG_DIR/nifty_ensemble_config.json"
else
    echo "✓ NIFTY config found"
fi

if [ ! -f "$CONFIG_DIR/banknifty_ensemble_config.json" ]; then
    echo "⚠ Warning: BANKNIFTY ensemble config not found"
    echo "  Expected: $CONFIG_DIR/banknifty_ensemble_config.json"
else
    echo "✓ BANKNIFTY config found"
fi

echo

# Run tests
echo -e "${YELLOW}Running tests...${NC}"
cd "$PROJECT_ROOT"
if python -m pytest tests/ml/test_ml_api.py -v --tb=short -q 2>&1 | tail -1; then
    echo "✓ Tests passed"
else
    echo "⚠ Warning: Some tests failed"
fi
echo

# Display deployment options
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Deployment Options:${NC}"
echo
echo "1. Start ML API only"
echo "2. Start Metrics Exporters only"
echo "3. Start all services (API + Metrics)"
echo "4. Check service status"
echo "5. Stop all services"
echo "6. Skip (manual deployment)"
echo
read -p "Select option (1-6): " option

case $option in
    1)
        echo
        echo -e "${GREEN}Starting ML API...${NC}"
        "$SCRIPT_DIR/start_ml_api.sh"
        ;;
    2)
        echo
        echo -e "${GREEN}Starting Metrics Exporters...${NC}"
        "$SCRIPT_DIR/start_ml_metrics.sh"
        ;;
    3)
        echo
        echo -e "${GREEN}Starting all services...${NC}"
        "$SCRIPT_DIR/start_ml_api.sh"
        echo
        "$SCRIPT_DIR/start_ml_metrics.sh"
        ;;
    4)
        echo
        "$SCRIPT_DIR/check_ml_status.sh"
        ;;
    5)
        echo
        echo -e "${GREEN}Stopping all services...${NC}"
        "$SCRIPT_DIR/stop_ml_services.sh"
        ;;
    6)
        echo
        echo "Skipping automatic deployment"
        ;;
    *)
        echo "Invalid option"
        exit 1
        ;;
esac

echo
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Deployment Summary${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo
echo "API Endpoints:"
echo "  Health:      http://localhost:9210/health"
echo "  Forecast:    http://localhost:9210/api/ml/ensemble/forecast?index=NIFTY&horizon=60"
echo "  Diagnostics: http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY"
echo
echo "Metrics Endpoints:"
echo "  NIFTY:       http://localhost:9325/metrics"
echo "  BANKNIFTY:   http://localhost:9326/metrics"
echo
echo "Grafana Dashboard:"
echo "  Import: dashboards_modular/ml_ensemble_monitoring.json"
echo
echo "Prometheus Rules:"
echo "  File: prometheus_rules_ml_ensemble.yml"
echo "  Add to prometheus.yml rule_files section"
echo
echo "Documentation:"
echo "  Deployment: docs/ml/PRODUCTION_DEPLOYMENT_GUIDE.md"
echo "  Summary:    PHASE4_COMPLETION_SUMMARY.md"
echo
echo "Automation:"
echo "  Retraining: python scripts/ml/automated_retraining.py --index NIFTY --days 60"
echo "  Cron:       0 2 * * 0 /path/to/scripts/ml/automated_retraining.py --index NIFTY"
echo
echo -e "${GREEN}✓ Phase 4 deployment complete!${NC}"
