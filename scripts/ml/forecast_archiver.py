from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from typing import List

try:  # Optional backoff utility (best-effort)
    from src.utils.backoff import sleep_ms as _sleep_ms  # type: ignore
except Exception:  # pragma: no cover - absence is acceptable
    _sleep_ms = None  # type: ignore

logger = logging.getLogger(__name__)


def _now_local() -> dt.datetime:
    # Use timezone-aware UTC to comply with time guard; local wall-clock not required here
    return dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0)


def _within_hours(now: dt.datetime, start_hm: str, end_hm: str) -> bool:
    try:
        sh, sm = [int(x) for x in start_hm.split(":", 1)]
        eh, em = [int(x) for x in end_hm.split(":", 1)]
        start = now.replace(hour=sh, minute=sm, second=0)
        end = now.replace(hour=eh, minute=em, second=0)
        if end <= start:
            # crosses midnight: treat as [start, 23:59:59] U [00:00, end]
            return (now >= start) or (now <= end)
        return start <= now <= end
    except Exception:
        return True


def _sleep_s(seconds: float) -> None:
    """Sleep with optional ms backoff helper (falls back to time.sleep)."""
    try:
        if _sleep_ms is not None:
            _sleep_ms(float(seconds) * 1000.0)
            return
    except Exception:  # pragma: no cover - defensive
        pass
    time.sleep(max(0.001, seconds))


def _get(url: str, timeout: float = 6.0) -> int:
    """Perform a lightweight GET; return HTTP status or 0 on failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
            return getattr(resp, "status", 200)
    except Exception as e:  # Broad but contained; surface via logging
        logger.debug("forecast_archiver: request failed", extra={"url": url, "error": str(e)})
        return 0


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Continuously ping JSON path-forecast to build archive bands")
    p.add_argument("--index", default="NIFTY")
    p.add_argument("--horizons", default="30,60", help="Comma-separated horizons; we'll use max(horizons)")
    p.add_argument("--interval", type=float, default=60.0, help="Seconds between calls")
    p.add_argument("--base-url", default="http://127.0.0.1:9500")
    p.add_argument("--expiry-tag", default="this_week")
    p.add_argument("--offset", default="0")
    p.add_argument("--window", type=int, default=60)
    p.add_argument("--k", type=int, default=15)
    p.add_argument("--mode", default="auto")
    p.add_argument("--bucket-ms", type=int, default=60_000)
    p.add_argument("--market-hours-only", action="store_true", help="Only run between --start-hhmm and --end-hhmm")
    p.add_argument("--start-hhmm", default="09:15")
    p.add_argument("--end-hhmm", default="15:30")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    try:
        horizons = [int(t.strip()) for t in str(args.horizons).split(',') if t.strip()]
    except Exception:
        horizons = []
    H = max(horizons) if horizons else 60

    base = args.base_url.rstrip('/')
    qbase = {
        "index": args.index.upper(),
        "expiry_tag": args.expiry_tag,
        "offset": args.offset,
        "window": str(int(args.window)),
        "k": str(int(args.k)),
        "mode": args.mode,
        "bucket_ms": str(int(args.bucket_ms)),
        # calibrate left as default True on server; we just trigger archival
    }

    logger.info(
        "forecast_archiver starting",
        extra={"index": qbase['index'], "max_horizon": H, "base": base},
    )
    while True:
        now = _now_local()
        if args.market_hours_only and not _within_hours(now, args.start_hhmm, args.end_hhmm):
            if not args.quiet:
                logger.debug(
                    "outside market hours",
                    extra={"now": now.isoformat(), "sleep_s": int(args.interval)},
                )
            _sleep_s(max(1.0, float(args.interval)))
            continue
        q = dict(qbase)
        q["horizon_minutes"] = str(int(H))
        url = f"{base}/api/ml/path_forecast_json?{urllib.parse.urlencode(q)}"
        status = _get(url, timeout=6.0)
        if not args.quiet:
            logger.info(
                "forecast ping",
                extra={"ts": int(time.time()), "status": status, "url": url},
            )
        _sleep_s(max(1.0, float(args.interval)))
        # Loop continues until interrupted
    # Should never reach here under normal operation


if __name__ == "__main__":  # Script entry point
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.info("forecast_archiver interrupted (KeyboardInterrupt)")
        raise SystemExit(0)
