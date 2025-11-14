import json
import time
from pathlib import Path

from src.data_access.unified_source import UnifiedDataSource, DataSourceConfig


def write_json(p: Path, obj) -> None:
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_cache_stats_status_hits_and_misses_default_poll(tmp_path):
    # Use a small positive poll interval to exercise the default (non-always-stat) branch
    status_file = tmp_path / "runtime_status.json"
    write_json(status_file, {"a": 1})

    cfg = DataSourceConfig(
        runtime_status_path=str(status_file),
        panels_dir=str(tmp_path),
        cache_ttl_seconds=10.0,
        watch_files=True,
        file_poll_interval=0.01,  # 10 ms
        enable_cache_stats=True,
    )

    uds = UnifiedDataSource()
    uds.reconfigure(cfg)

    # First read -> miss + read
    d1 = uds.get_runtime_status()
    assert d1 == {"a": 1}
    s1 = uds.get_cache_stats()
    assert s1["status"]["misses"] >= 1
    assert s1["status"]["reads"] >= 1

    # Second read shortly after -> should be a hit
    d2 = uds.get_runtime_status()
    assert d2 == {"a": 1}
    s2 = uds.get_cache_stats()
    assert s2["status"]["hits"] >= s1["status"].get("hits", 0) + 1

    # Wait to exceed poll interval, then modify the file and read again -> miss + read
    time.sleep(0.02)
    write_json(status_file, {"a": 2})
    # Small delay to ensure mtime progression on all filesystems
    time.sleep(0.02)

    d3 = uds.get_runtime_status()
    assert d3 == {"a": 2}
    s3 = uds.get_cache_stats()
    assert s3["status"]["misses"] >= s2["status"]["misses"] + 1
    assert s3["status"]["reads"] >= s2["status"]["reads"] + 1
