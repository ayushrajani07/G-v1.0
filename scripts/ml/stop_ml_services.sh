#!/bin/bash
# Stop ML Ensemble Services
# Part of Phase 4: Production Deployment

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

LOG_DIR="${PROJECT_ROOT}/logs"

# Function to stop service by PID file
stop_service() {
    local SERVICE_NAME=$1
    local PID_FILE="${LOG_DIR}/${SERVICE_NAME}.pid"
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Stopping $SERVICE_NAME (PID: $PID)..."
            kill "$PID"
            
            # Wait for graceful shutdown
            for i in {1..10}; do
                if ! ps -p "$PID" > /dev/null 2>&1; then
                    echo "✓ $SERVICE_NAME stopped"
                    rm "$PID_FILE"
                    return 0
                fi
                sleep 1
            done
            
            # Force kill if still running
            if ps -p "$PID" > /dev/null 2>&1; then
                echo "Force stopping $SERVICE_NAME..."
                kill -9 "$PID"
                rm "$PID_FILE"
            fi
        else
            echo "⚠ $SERVICE_NAME not running (stale PID file)"
            rm "$PID_FILE"
        fi
    else
        echo "⚠ $SERVICE_NAME PID file not found"
    fi
}

echo "Stopping ML Ensemble Services..."
echo

# Stop services
stop_service "ml_api"
stop_service "ml_metrics_nifty"
stop_service "ml_metrics_banknifty"

echo
echo "✓ All ML services stopped"
