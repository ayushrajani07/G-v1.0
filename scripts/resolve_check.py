from datetime import date, timedelta
from src.broker.kite.expiries import resolve_expiry_rule

class DummyProvider:
    def get_expiry_dates(self, index_symbol: str):
        # Fixed reference date for deterministic output: 2025-10-27 (Mon)
        today = date(2025, 10, 27)
        # Next 8 Thursdays from today
        d = today
        while d.weekday() != 3:
            d += timedelta(days=1)
        thursdays = [d + timedelta(days=7 * i) for i in range(8)]
        # A couple of extra non-Thursday dates to test filtering tolerance
        extras = [today - timedelta(days=7), today + timedelta(days=2)]
        return thursdays + extras


def main():
    prov = DummyProvider()
    for rule in ["this_week", "next_week", "this_month", "next_month"]:
        r = resolve_expiry_rule(prov, "NIFTY", rule)
        print(f"{rule}: {r}")


if __name__ == "__main__":
    main()
