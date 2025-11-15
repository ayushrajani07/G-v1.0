from __future__ import annotations

import argparse
import logging
import sys
import time
try:  # Optional backoff helper (best-effort)
    from src.utils.backoff import sleep_ms as _sleep_ms  # type: ignore
except Exception:  # pragma: no cover
    _sleep_ms = None  # type: ignore

logger = logging.getLogger(__name__)

def _sleep_s(_sec: float) -> None:
    try:
        if _sleep_ms:
            _sleep_ms(float(_sec) * 1000.0)
            return
    except Exception:
        pass
    time.sleep(_sec)
from pathlib import Path
from typing import Optional, List

import urllib.request
from src.error_handling import safe_write_text, safe_append_line  # type: ignore

ROOT = Path(__file__).resolve().parents[2]


def fetch_csv(url: str, timeout: int = 10) -> str:
    """Fetch text content from URL; raises on failure.

    Caller wraps this for granular logging; network failures are not fatal for the loop.
    """
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
        return resp.read().decode("utf-8", errors="ignore")


def main() -> None:
    ap = argparse.ArgumentParser(description="Archive move stats snapshots from diagnostics endpoint")
    ap.add_argument("--indices", default="NIFTY", help="Comma-separated indices e.g., NIFTY,BANKNIFTY")
    ap.add_argument("--horizons", default="1", help="Comma-separated horizons e.g., 1,30,60")
    ap.add_argument("--base-url", default="http://127.0.0.1:9500", help="Dashboard API base URL")
    ap.add_argument("--window-minutes", type=int, default=180)
    ap.add_argument("--interval", type=int, default=60, help="Poll interval seconds")
    ap.add_argument("--prob-threshold", type=float, default=0.6)
    ap.add_argument("--outdir", default=str(ROOT / "data" / "ml" / "move_stats"))
    args = ap.parse_args()

    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    indices = [s.strip().upper() for s in (args.indices or "").split(",") if s.strip()]
    horizons = [s.strip() for s in (args.horizons or "").split(",") if s.strip()]

    header_cols: List[str] = [
        "timestamp",
        "index",
        "horizon",
        "avg_move_probability",
        "move_high_prob_share",
        "move_mag_p10",
        "move_mag_p50",
        "move_mag_p90",
        "move_last_prob",
        "move_last_mag",
        "window_minutes",
    ]

    logger.info("move_stats_archiver starting", extra={"indices": indices, "horizons": horizons, "outdir": str(out_dir)})
    try:
        while True:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            for idx in indices:
                for hz in horizons:
                    url = (
                        f"{args.base_url.rstrip('/')}/api/ml/diagnostics?index={idx}&horizon={hz}"
                        f"&model=sk_hgb_residual&window_minutes={int(args.window_minutes)}&include_move_stats=true"
                        f"&move_prob_threshold={args.prob_threshold}"
                    )
                    try:
                        csv_text = fetch_csv(url)
                    except Exception as e:
                        logger.warning("fetch failed", extra={"index": idx, "horizon": hz, "error": str(e)})
                        continue
                    lines = csv_text.splitlines()
                    if not lines or len(lines) < 2:
                        logger.debug("empty or short diagnostics CSV", extra={"index": idx, "horizon": hz})
                        continue
                    cols = lines[0].split(",")
                    col_idx = {name: i for i, name in enumerate(cols)}
                    row = lines[1].split(",") if len(lines) > 1 else []
                    def gv(name: str) -> str:
                        i = col_idx.get(name, -1)
                        return row[i] if (0 <= i < len(row)) else ""
                    row_vals: List[str] = [
                        ts,
                        idx,
                        str(hz),
                        gv("avg_move_probability"),
                        gv("move_high_prob_share"),
                        gv("move_mag_p10"),
                        gv("move_mag_p50"),
                        gv("move_mag_p90"),
                        gv("move_last_prob"),
                        gv("move_last_mag"),
                        str(int(args.window_minutes)),
                    ]
                    fp = out_dir / f"{idx}_{hz}.csv"
                    try:
                        from src.storage.csvio import api as _csvio_api  # type: ignore
                        _csvio_api.append_one(str(fp), row_vals, header_cols)
                    except Exception:
                        try:
                            if not fp.exists():
                                safe_write_text(fp, ",".join(header_cols) + "\n")
                            safe_append_line(fp, ",".join(row_vals))
                        except Exception as e2:  # pragma: no cover - rare
                            logger.error("fallback append failed", extra={"file": str(fp), "error": str(e2)})
            _sleep_s(max(1, int(args.interval)))
    except KeyboardInterrupt:
        logger.info("move_stats_archiver interrupted (KeyboardInterrupt)")
    except Exception as e:
        logger.error("move_stats_archiver fatal loop error", extra={"error": str(e)})


if __name__ == "__main__":  # CLI entry
    # Initialize basic logging config if not already configured
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
