import datetime


def test_csv_aggregator_prev_close_loads_without_nameerror(tmp_path):
    from src.storage.csv_aggregator import CsvAggregator

    base_dir = tmp_path
    index = "NIFTY"

    # Create an overview CSV for the previous day.
    today = datetime.date(2026, 1, 27)
    prev_day = today - datetime.timedelta(days=1)

    overview_dir = base_dir / "overview" / index
    overview_dir.mkdir(parents=True, exist_ok=True)
    fp = overview_dir / f"{prev_day.strftime('%Y-%m-%d')}.csv"

    fp.write_text(
        "timestamp,index,index_price,tp\n"
        "27-01-2026 09:15:00,NIFTY,25000,123\n",
        encoding="utf-8",
    )

    class _NullLogger:
        def debug(self, *a, **k):
            pass

        def info(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass

        def error(self, *a, **k):
            pass

    agg = CsvAggregator(base_dir=str(base_dir), logger=_NullLogger(), metrics=None)

    # Should read the previous day's file via csv.DictReader and not crash.
    agg._ensure_prev_close_loaded(index=index, date_key=today.strftime('%Y-%m-%d'))

    assert agg._index_prev_close.get(index) == 25000.0
    assert agg._tp_prev_close.get(index) == 123.0
