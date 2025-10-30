#!/usr/bin/env python3
"""
Stack health probe for G6 baseline.

Defaults:
- Web API only: http://127.0.0.1:9500/openapi.json -> 200

Optional checks (enabled via --only or env):
- Grafana:       http://127.0.0.1:3002/api/health -> 200
- Prometheus:    http://127.0.0.1:9091/-/ready -> 200
- Metrics:       http://127.0.0.1:9108/metrics -> 200
- Overlay:       http://127.0.0.1:9109/metrics -> 200

Environment toggles (truthy values: 1,true,yes,on):
- G6_HEALTH_INCLUDE_ALL=1       -> include all optional checks
- G6_HEALTH_INCLUDE_GRAFANA=1   -> include Grafana with Web API

Use CLI flags to override ports/hosts, change timeout/retries, and to select a subset.
Exit code is non-zero if any selected check fails.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple
import os


@dataclass
class Endpoint:
    name: str
    url: str
    expect: int = 200


def fetch_status(url: str, timeout: float) -> Tuple[int, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "g6-health/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            code = resp.getcode() or 0
            # try to sniff JSON to provide quick info
            ctype = resp.headers.get("Content-Type", "")
            body_snip = ""
            if "json" in ctype.lower():
                try:
                    payload = json.loads(resp.read().decode("utf-8"))
                    # keep it tiny
                    body_snip = json.dumps(payload)[:160]
                except Exception:
                    body_snip = "<json>"
            return code, body_snip
    except urllib.error.HTTPError as e:
        return int(e.code), f"HTTPError:{e.reason}"
    except urllib.error.URLError as e:
        return 0, f"URLError:{getattr(e, 'reason', e)}"
    except Exception as e:
        return 0, f"Exception:{e.__class__.__name__}:{e}"


def probe(endpoints: Iterable[Endpoint], timeout: float, retries: int, delay: float) -> Dict[str, Dict[str, object]]:
    results: Dict[str, Dict[str, object]] = {}
    for ep in endpoints:
        code = 0
        note = ""
        for attempt in range(1, retries + 1):
            code, note = fetch_status(ep.url, timeout)
            if code == ep.expect:
                break
            time.sleep(delay)
        results[ep.name] = {
            "url": ep.url,
            "got": code,
            "expect": ep.expect,
            "ok": code == ep.expect,
            "note": note,
        }
    return results


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description="Probe G6 observability endpoints")
    p.add_argument("--host", default="127.0.0.1", help="Host/IP for all services (default: 127.0.0.1)")
    p.add_argument("--grafana-port", type=int, default=3002)
    p.add_argument("--prom-port", type=int, default=9091)
    p.add_argument("--web-port", type=int, default=9500)
    p.add_argument("--metrics-port", type=int, default=9108)
    p.add_argument("--overlay-port", type=int, default=9109)
    p.add_argument("--timeout", type=float, default=2.5, help="Per-attempt timeout seconds")
    p.add_argument("--retries", type=int, default=5, help="Attempts per endpoint")
    p.add_argument("--delay", type=float, default=0.6, help="Delay between retries in seconds")
    p.add_argument(
        "--only",
        choices=["grafana", "prometheus", "web", "metrics", "overlay"],
        nargs="*",
        help="If provided, probe only this subset",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON summary only")
    args = p.parse_args(argv)

    h = args.host
    all_eps = [
        Endpoint("grafana", f"http://{h}:{args.grafana_port}/api/health"),
        Endpoint("prometheus", f"http://{h}:{args.prom_port}/-/ready"),
        Endpoint("web", f"http://{h}:{args.web_port}/openapi.json"),
        Endpoint("metrics", f"http://{h}:{args.metrics_port}/metrics"),
        Endpoint("overlay", f"http://{h}:{args.overlay_port}/metrics"),
    ]
    # Default: Web API only
    eps = [e for e in all_eps if e.name == "web"]
    # Env toggles
    truthy = {"1", "true", "yes", "on"}
    if str(os.getenv("G6_HEALTH_INCLUDE_ALL", "")).lower() in truthy:
        eps = all_eps
    elif str(os.getenv("G6_HEALTH_INCLUDE_GRAFANA", "")).lower() in truthy:
        eps = [e for e in all_eps if e.name in {"web", "grafana"}]
    # CLI --only overrides everything
    if args.only:
        include = set(args.only)
        eps = [e for e in all_eps if e.name in include]

    out = probe(eps, timeout=args.timeout, retries=args.retries, delay=args.delay)

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("--- Stack Health ---")
        for name, info in out.items():
            ok = "OK" if info["ok"] else "FAIL"
            exp = info["expect"]
            got = info["got"]
            print(f"{name:10s} [{ok}] expect={exp} got={got} url={info['url']}")
            if info.get("note"):
                print(f"  note: {info['note']}")

    # exit non-zero if any failed
    rc = 0 if all(v.get("ok") for v in out.values()) else 2
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
