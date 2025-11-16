#!/bin/bash
# Start ML Ensemble Metrics Exporters
# Part of Phase 4: Production Deployment

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
NIFTY_PORT="${ML_METRICS_NIFTY_PORT:-9325}"
BANKNIFTY_PORT="${ML_METRICS_BANKNIFTY_PORT:-9326}"
INTERVAL="${ML_METRICS_INTERVAL:-60}"
LOG_DIR="${PROJECT_ROOT}/logs"

# Create log directory
mkdir -p "$LOG_DIR"

# Function to start exporter for an index
start_exporter() {
    local INDEX=$1
    local PORT=$2
    local CONFIG="${PROJECT_ROOT}/configs/ml/${INDEX,,}_ensemble_config.json"
    local LOG_FILE="${LOG_DIR}/ml_metrics_${INDEX,,}.log"
    local PID_FILE="${LOG_DIR}/ml_metrics_${INDEX,,}.pid"
    
    # Check if config exists
    if [ ! -f "$CONFIG" ]; then
        echo "⚠ Config not found for $INDEX: $CONFIG"
        return 1
    fi
    
    # Check if already running
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "$INDEX metrics exporter already running (PID: $PID)"
            return 0
        else
            rm "$PID_FILE"
        fi
    fi
    
    # Start exporter
    echo "Starting $INDEX metrics exporter..."
    echo "  Port: $PORT"
    echo "  Interval: ${INTERVAL}s"
    echo "  Logs: $LOG_FILE"
    
    cd "$PROJECT_ROOT"
    nohup python scripts/ml/ml_ensemble_metrics_exporter.py \
        --index "$INDEX" \
        --config "$CONFIG" \
        --port "$PORT" \
        --interval "$INTERVAL" \
        > "$LOG_FILE" 2>&1 &
    
    local PID=$!
    echo $PID > "$PID_FILE"
    
    # Wait and verify
    sleep 2
    if ps -p $PID > /dev/null; then
        echo "✓ $INDEX exporter started (PID: $PID)"
        
        # Test metrics endpoint
        sleep 1
        if curl -s "http://localhost:$PORT/metrics" > /dev/null 2>&1; then
            echo "✓ $INDEX metrics endpoint responding"
        else
            echo "⚠ $INDEX exporter started but metrics not available yet"
        fi
    else
        echo "✗ Failed to start $INDEX exporter"
        rm "$PID_FILE"
        return 1
    fi
}

# Start exporters
echo "Starting ML Ensemble Metrics Exporters..."
echo

start_exporter "NIFTY" "$NIFTY_PORT"
echo

start_exporter "BANKNIFTY" "$BANKNIFTY_PORT"
echo

echo "✓ All metrics exporters started"
echo
echo "Metrics endpoints:"
echo "  NIFTY:     http://localhost:$NIFTY_PORT/metrics"
echo "  BANKNIFTY: http://localhost:$BANKNIFTY_PORT/metrics"
