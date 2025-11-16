#!/bin/bash
# Check ML Ensemble Services Status
# Part of Phase 4: Production Deployment

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

LOG_DIR="${PROJECT_ROOT}/logs"

# ANSI color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check service status
check_service() {
    local SERVICE_NAME=$1
    local PID_FILE="${LOG_DIR}/${SERVICE_NAME}.pid"
    local ENDPOINT=$2
    
    echo -n "$SERVICE_NAME: "
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo -e "${GREEN}RUNNING${NC} (PID: $PID)"
            
            # Check endpoint if provided
            if [ -n "$ENDPOINT" ]; then
                if curl -s "$ENDPOINT" > /dev/null 2>&1; then
                    echo "  └─ Endpoint: ${GREEN}OK${NC} ($ENDPOINT)"
                else
                    echo "  └─ Endpoint: ${RED}FAILED${NC} ($ENDPOINT)"
                fi
            fi
            return 0
        else
            echo -e "${RED}STOPPED${NC} (stale PID file)"
            return 1
        fi
    else
        echo -e "${RED}STOPPED${NC} (no PID file)"
        return 1
    fi
}

echo "ML Ensemble Services Status"
echo "============================"
echo

# Check services
check_service "ml_api" "http://localhost:9210/health"
echo

check_service "ml_metrics_nifty" "http://localhost:9325/metrics"
echo

check_service "ml_metrics_banknifty" "http://localhost:9326/metrics"
echo

echo "============================"
echo

# Show recent log entries
if [ -f "$LOG_DIR/ml_api.log" ]; then
    echo "Recent API log entries:"
    tail -5 "$LOG_DIR/ml_api.log" | sed 's/^/  /'
    echo
fi

# Check for errors in logs
ERROR_COUNT=$(grep -i "error" "$LOG_DIR"/*.log 2>/dev/null | wc -l)
if [ $ERROR_COUNT -gt 0 ]; then
    echo -e "${YELLOW}⚠ Found $ERROR_COUNT error(s) in logs${NC}"
    echo "  Check: tail -f $LOG_DIR/*.log"
else
    echo -e "${GREEN}✓ No errors in recent logs${NC}"
fi
