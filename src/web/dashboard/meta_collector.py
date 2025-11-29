"""
Meta-Data Collector for Forecast Intelligence (Phase 13).

Logs forecast events (inputs + predictions) to a JSONL file for later training of
meta-models (Stacking/Learned Weighting).

Schema:
{
  "ts": <epoch_ms>,
  "index": "NIFTY",
  "horizon": 60,
  "inputs": {
    "underlying": 18000.0,
    "avg_iv": 0.15,
    "minutes_to_expiry": 300.0,
    "recent_volatility": 0.01  # derived if possible
  },
  "predictions": {
    "p50": 18050.0,
    "p10": 17900.0,
    "p90": 18200.0
  },
  "components": {
    "baseline": 18020.0,
    "gbrt_residual": 5.0,
    "retrieval_forecast": 18040.0
  },
  "weights": {
    "gbrt": 0.8,
    "retrieval": 0.2
  },
  "confidence": 0.85
}
"""
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict

_LOG = logging.getLogger(__name__)
_LOCK = threading.Lock()
_FILE_PATH = Path("data/ml/meta_data/forecast_events.jsonl")
_ENABLED = os.environ.get("G6_META_COLLECTOR_ENABLE", "1") == "1"

def log_forecast_event(
    index: str,
    horizon: int,
    context: Dict[str, Any],
    forecast_data: Dict[str, float],
    metadata: Dict[str, Any],
    component_preds: Dict[str, float] = None
):
    """Log a forecast event to JSONL."""
    if not _ENABLED:
        return

    try:
        event = {
            "ts": int(time.time() * 1000),
            "index": index,
            "horizon": horizon,
            "inputs": {
                "underlying": context.get("underlying"),
                "avg_iv": context.get("avg_iv"),
                "minutes_to_expiry": context.get("minutes_to_expiry"),
            },
            "predictions": forecast_data,
            "weights": metadata.get("weights", {}),
            "confidence": metadata.get("confidence", 0.0),
        }
        
        if component_preds:
            event["components"] = component_preds

        # Ensure directory exists
        if not _FILE_PATH.parent.exists():
            _FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

        with _LOCK:
            with open(_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
                
    except Exception as e:
        _LOG.warning(f"Failed to log forecast event: {e}")
