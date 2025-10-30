#!/usr/bin/env python3
"""Resilient starter for the local dashboard FastAPI server.

- Tries a list of candidate ports and starts on the first free one.
- Falls back automatically if a port is in use (e.g., previous uvicorn still running).
- Optional --reload for dev inner loop.

Usage (Windows PowerShell):
    venv\\Scripts\\python.exe scripts/start_dashboard_api.py --reload

Outputs the chosen URL so callers (or tasks) can open a browser.
"""
from __future__ import annotations

import argparse
import socket
import sys
import os

# Ensure project root is on sys.path so 'src.*' imports work even when
# uvicorn reload changes the working directory.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) != 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ports", nargs="*", type=int, default=[9500, 8003])
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    try:
        import uvicorn  # type: ignore
    except Exception:
        print("error: uvicorn not installed. pip install uvicorn[standard]", file=sys.stderr)
        return 2

    host = args.host
    candidates = list(args.ports) if args.ports else [9500, 8003]

    port = None
    for p in candidates:
        if is_port_free(p, host=host):
            port = p
            break
    if port is None:
        # All candidates busy; pick the first and hope reload server can reuse
        port = candidates[0]

    cfg = uvicorn.Config(
        "src.web.dashboard.app:app",
        host=host,
        port=port,
        reload=bool(args.reload),
        log_level="info",
    )
    print(f"Starting dashboard API on http://{host}:{port}")
    server = uvicorn.Server(cfg)
    # uvicorn.Server.run() returns None; return 0 on successful invocation
    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
