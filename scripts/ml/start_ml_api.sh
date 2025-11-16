#!/bin/bash
# Start ML Ensemble API Server
# Part of Phase 4: Production Deployment

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
API_HOST="${ML_API_HOST:-0.0.0.0}"
API_PORT="${ML_API_PORT:-9210}"
LOG_DIR="${PROJECT_ROOT}/logs"
PID_FILE="${LOG_DIR}/ml_api.pid"

# Create log directory
mkdir -p "$LOG_DIR"

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "ML API is already running (PID: $PID)"
        exit 0
    else
        echo "Removing stale PID file"
        rm "$PID_FILE"
    fi
fi

# Start API server
echo "Starting ML Ensemble API server..."
echo "  Host: $API_HOST"
echo "  Port: $API_PORT"
echo "  Logs: $LOG_DIR/ml_api.log"

cd "$PROJECT_ROOT"
nohup python -m src.web.api.ml_ensemble \
    --host "$API_HOST" \
    --port "$API_PORT" \
    > "$LOG_DIR/ml_api.log" 2>&1 &

API_PID=$!
echo $API_PID > "$PID_FILE"

# Wait a moment and check if it started
sleep 2
if ps -p $API_PID > /dev/null; then
    echo "✓ ML API started successfully (PID: $API_PID)"
    
    # Test health endpoint
    sleep 1
    if curl -s "http://localhost:$API_PORT/health" > /dev/null 2>&1; then
        echo "✓ API health check passed"
    else
        echo "⚠ API started but health check failed"
    fi
else
    echo "✗ Failed to start ML API"
    rm "$PID_FILE"
    exit 1
fi
