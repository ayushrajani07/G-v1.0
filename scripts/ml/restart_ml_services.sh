#!/bin/bash
# Restart ML Ensemble Services
# Part of Phase 8: Production Deployment & Stabilization

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "="
echo "Restarting ML Ensemble Services"
echo "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "="
echo

# Stop existing services
echo "Step 1: Stopping existing services..."
"$SCRIPT_DIR/stop_ml_services.sh"
echo

# Wait for clean shutdown
echo "Waiting for clean shutdown..."
sleep 2
echo

# Start API server
echo "Step 2: Starting API server..."
"$SCRIPT_DIR/start_ml_api.sh"
echo

# Wait for API to be ready
echo "Waiting for API to be ready..."
sleep 3
echo

# Start metrics exporters
echo "Step 3: Starting metrics exporters..."
"$SCRIPT_DIR/start_ml_metrics.sh"
echo

# Verify all services
echo "Step 4: Verifying services..."
echo

# Check API
API_PORT="${ML_API_PORT:-9210}"
if curl -s "http://localhost:$API_PORT/health" > /dev/null 2>&1; then
    echo "✓ ML API is responding"
else
    echo "✗ ML API health check failed"
    exit 1
fi

# Check metrics exporters
NIFTY_PORT="${ML_METRICS_NIFTY_PORT:-9325}"
BANKNIFTY_PORT="${ML_METRICS_BANKNIFTY_PORT:-9326}"

if curl -s "http://localhost:$NIFTY_PORT/metrics" > /dev/null 2>&1; then
    echo "✓ NIFTY metrics exporter is responding"
else
    echo "⚠ NIFTY metrics exporter may not be ready yet"
fi

if curl -s "http://localhost:$BANKNIFTY_PORT/metrics" > /dev/null 2>&1; then
    echo "✓ BANKNIFTY metrics exporter is responding"
else
    echo "⚠ BANKNIFTY metrics exporter may not be ready yet"
fi

echo
echo "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "="
echo "✓ ML Ensemble Services Restarted Successfully"
echo "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "="
echo
echo "Service endpoints:"
echo "  API:       http://localhost:$API_PORT"
echo "  Health:    http://localhost:$API_PORT/health"
echo "  NIFTY:     http://localhost:$NIFTY_PORT/metrics"
echo "  BANKNIFTY: http://localhost:$BANKNIFTY_PORT/metrics"
echo
echo "Logs:"
echo "  API:       logs/ml_api.log"
echo "  NIFTY:     logs/ml_metrics_nifty.log"
echo "  BANKNIFTY: logs/ml_metrics_banknifty.log"
