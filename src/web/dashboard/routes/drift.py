from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from src.analytics.ml.drift import DriftMonitor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/drift", tags=["drift"])

# Initialize monitor (singleton-like usage for dashboard)
_monitor = DriftMonitor()

@router.get("/history", response_model=List[Dict[str, Any]])
async def get_drift_history(
    index: Optional[str] = Query(None, description="Filter by index name (e.g., NIFTY)"),
    limit: int = Query(100, description="Maximum number of records to return")
) -> List[Dict[str, Any]]:
    """Get recent drift history records."""
    try:
        return _monitor.load_history(index=index, limit=limit)
    except Exception as e:
        logger.error(f"Failed to load drift history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/accuracy", response_model=Dict[str, float])
async def get_accuracy_metrics(
    index: str = Query(..., description="Index name (e.g., NIFTY)"),
    window: int = Query(30, description="Number of recent records to analyze")
) -> Dict[str, float]:
    """Get long-term accuracy metrics (MAE, MAPE trends)."""
    try:
        return _monitor.get_long_term_accuracy(index=index, window=window)
    except Exception as e:
        logger.error(f"Failed to calculate accuracy metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
