"""
Drift Baseline Age Check (Phase 12).

Checks the age of the active drift manifest.
If the baseline is older than 7 days, it indicates that the drift thresholds
might be stale and need recalibration.

Usage:
    python scripts/ml/check_drift_baseline_age.py --max-age-days 7
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
_LOG = logging.getLogger(__name__)

MANIFEST_DIR = Path("metrics/drift_manifests")
LATEST_LINK = MANIFEST_DIR / "latest.json"

def check_age(max_days: int) -> bool:
    """Check if latest manifest is within max_days. Returns True if OK, False if stale."""
    if not LATEST_LINK.exists():
        _LOG.warning(f"No active drift manifest found at {LATEST_LINK}")
        return False

    try:
        with open(LATEST_LINK, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        gen_at_str = data.get("generated_at")
        if not gen_at_str:
            _LOG.error("Manifest missing 'generated_at' field")
            return False
            
        # Parse ISO format (handle Z if present)
        gen_at_str = gen_at_str.replace("Z", "+00:00")
        gen_at = datetime.fromisoformat(gen_at_str)
        
        # Ensure timezone awareness
        if gen_at.tzinfo is None:
            gen_at = gen_at.replace(tzinfo=timezone.utc)
            
        now = datetime.now(timezone.utc)
        age = now - gen_at
        
        _LOG.info(f"Active Manifest: {data.get('signature', 'unknown')}")
        _LOG.info(f"Generated At: {gen_at}")
        _LOG.info(f"Age: {age}")
        
        if age > timedelta(days=max_days):
            _LOG.error(f"BASELINE STALE! Age {age.days} days > limit {max_days} days.")
            _LOG.error("Run 'python scripts/ml/calibrate_drift_thresholds.py' to recalibrate.")
            return False
            
        _LOG.info("Baseline age is within limits.")
        return True
        
    except Exception as e:
        _LOG.error(f"Failed to check manifest age: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-days", type=int, default=7, help="Max allowed age in days")
    args = parser.parse_args()
    
    ok = check_age(args.max_age_days)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
