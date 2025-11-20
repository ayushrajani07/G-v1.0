"""Persistent Uvicorn runner for dashboard app.

Usage (PowerShell):
  python run_dashboard_server.py --port 9510 --host 0.0.0.0 --reload  # optional reload

Features:
- Lifespan disabled (avoid shutdown hooks causing early exit)
- Automatic retry on port in use or unexpected crash
- Graceful Ctrl+C handling
- Optional --reload passthrough
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from typing import Any

import uvicorn
import signal
from types import FrameType

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9510)
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    ap.add_argument("--max-restarts", type=int, default=10)
    ap.add_argument("--restart-delay", type=float, default=2.0)
    return ap.parse_args()


def run_server(args: argparse.Namespace) -> int:
    from src.web.dashboard.app import app  # local import; raises if missing

    restarts = 0
    # Interrupt handling state (ignore first SIGINT/SIGTERM to avoid auto injected signal)
    interrupt_count = 0

    def make_handler(sig_name: str):
        def _handler(signum: int, frame: FrameType | None) -> None:  # noqa: D401
            # Fully ignore external SIGINT/SIGTERM (auto injected) to keep server alive.
            # For manual shutdown, user should taskkill the process.
            nonlocal interrupt_count
            interrupt_count += 1
            if interrupt_count == 1:
                print(f"[runner] received {sig_name} (count=1) - ignored (server persists). Use taskkill /PID <pid> /F to stop.")
            elif interrupt_count % 10 == 0:
                print(f"[runner] received {sig_name} {interrupt_count} times - still ignoring.")
        return _handler

    # Install custom handlers once outside retry loop
    try:
        signal.signal(signal.SIGINT, make_handler('SIGINT'))
    except (ValueError, OSError, RuntimeError):  # pragma: no cover
        pass
    try:
        signal.signal(signal.SIGTERM, make_handler('SIGTERM'))
    except (ValueError, OSError, RuntimeError):  # pragma: no cover
        pass
    while restarts <= args.max_restarts:
        config = uvicorn.Config(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
            reload=args.reload,
            lifespan="off",  # disable lifespan to prevent premature shutdown
            timeout_keep_alive=30,
        )
        server = uvicorn.Server(config)
        print(f"[runner] starting uvicorn host={args.host} port={args.port} reload={args.reload} attempt={restarts+1}")
        try:
            rc = server.run()
            # server.run() returns True if started successfully & wasn't stopped by error
            if rc is True:
                print("[runner] server stopped gracefully")
                return 0
            else:
                print("[runner] server returned False, will retry")
        except KeyboardInterrupt:
            # Should never trigger now (handlers do not raise); continue loop.
            print("[runner] unexpected KeyboardInterrupt caught; ignoring and continuing")
            continue
        except Exception as e:  # noqa: BLE001
            print("[runner] crash detected:")
            traceback.print_exc()
        restarts += 1
        if restarts <= args.max_restarts:
            print(f"[runner] sleeping {args.restart_delay}s before restart")
            time.sleep(args.restart_delay)
    print("[runner] exceeded max restarts; exiting with failure")
    return 1


def main() -> None:
    args = parse_args()
    code = run_server(args)
    sys.exit(code)

if __name__ == "__main__":
    main()
