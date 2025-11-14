import sys
import json
import argparse
from urllib.request import urlopen, Request

DEFAULT_BASE = "http://127.0.0.1:9500"
INTEGRITY = "/api/diag/advisor_integrity"
AGE = "/api/ml/universal_advisor/generated_at_age_minutes"


def _get(url: str, timeout: float = 5.0):
    req = Request(url, headers={"User-Agent": "probe/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        code = resp.getcode()
        data = resp.read()
        return code, json.loads(data.decode("utf-8"))


def run_probe(base_url: str = DEFAULT_BASE, warn_age_minutes: float = 15.0) -> int:
    """Run integrity + freshness probe.

    Returns exit codes:
      0: OK (integrity good, age <= warn threshold)
      1: WARN (integrity good, age > warn threshold)
      2: FAIL (integrity failure)
      3: FAIL (freshness retrieval failure)
    """
    # Integrity
    try:
        code, data = _get(base_url.rstrip("/") + INTEGRITY, timeout=5.0)
        if code != 200:
            print(f"integrity_fail status={code}")
            return 2
        if not data.get("present") or not data.get("openapi_present"):
            print("integrity_fail present/openapi=false")
            return 2
    except Exception as e:
        print(f"integrity_error: {e}")
        return 2

    # Age
    try:
        code, data = _get(base_url.rstrip("/") + AGE, timeout=5.0)
        if code != 200:
            print(f"age_fail status={code}")
            return 3
        age = data.get("age_minutes")
        if age is None:
            print("age_fail missing age_minutes")
            return 3
        if float(age) > float(warn_age_minutes):
            print(f"age_warn age_minutes={age}")
            return 1
        print(f"ok age_minutes={age}")
        return 0
    except Exception as e:
        print(f"age_error: {e}")
        return 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Advisor health probe")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="Base URL of the Dashboard API (default: %(default)s)")
    parser.add_argument("--warn-age-minutes", type=float, default=15.0, help="Warn if age_minutes exceeds this value (default: %(default)s)")
    args = parser.parse_args(argv)
    return run_probe(base_url=args.base_url, warn_age_minutes=args.warn_age_minutes)


if __name__ == "__main__":
    sys.exit(main())
