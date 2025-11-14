from pathlib import Path
from src.path_forecast.config_structs import RetrievalConfig
from src.path_forecast.retrieval import RetrievalPathForecaster


def write_day(root: Path, index: str, expiry: str, offset: str, date_str: str, tp_values):
    day_dir = root / index / expiry / offset
    day_dir.mkdir(parents=True, exist_ok=True)
    p = day_dir / f"{date_str}.csv"
    with p.open("w", encoding="utf-8") as f:
        f.write("ts,tp\n")
        t = 0
        for v in tp_values:
            f.write(f"{t},{float(v)}\n"); t += 60000
    return p


def build_recent(vals):
    return [[float(v)] for v in vals]


def main():
    tmp_root = Path.cwd()/".tmp_pf_test_weighted"
    if tmp_root.exists():
        import shutil; shutil.rmtree(tmp_root)
    index, expiry, offset = "NIFTY", "this_week", "0"
    recent = [200 + i*0.05 for i in range(60)]
    day_close = recent + [recent[-1] + (i+1)*0.1 for i in range(20)]
    day_far = [v + 5.0 for v in recent] + [recent[-1] + 5.0 + (i+1)*0.5 for i in range(20)]
    write_day(tmp_root, index, expiry, offset, "2025-11-07", day_close)
    write_day(tmp_root, index, expiry, offset, "2025-11-06", day_far)
    cfg = RetrievalConfig(root=tmp_root, expiry_tag=expiry, offset=offset, window=60, k=2, weight_mode="inv_dist", use_ann=False)
    f = RetrievalPathForecaster(cfg)
    try:
        f.forecast_path(build_recent(recent), context={"index": index, "now_ms": 0, "live_rows": []}, horizon_minutes=15)
        print("OK")
    except Exception as e:
        print("EXC:", type(e).__name__, e)
    print("META:", f.last_meta)

if __name__ == "__main__":
    main()
