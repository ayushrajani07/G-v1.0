from __future__ import annotations

import os
from pathlib import Path


def test_auto_create_uses_safe_write(monkeypatch, tmp_path):
    # Ensure env flag triggers auto-create
    monkeypatch.setenv('G6_CONFIG_AUTO_CREATE', '1')
    # Clear EnvConfig cache to pick up env mutation
    from src.config.env_config import EnvConfig
    try:
        EnvConfig.clear_cache()
    except Exception:
        pass

    recorded: dict[str, str] = {}

    from src.error_handling import safe_write_text
    # Wrap underlying safe_write_text to record invocation
    def recording(path, content, **kwargs):  # pragma: no cover - wrapper logic
        recorded['path'] = str(path)
        recorded['size'] = str(len(content))
        return True
    monkeypatch.setattr('src.error_handling.safe_write_text', recording)

    from src.config.loader import load_and_validate_config, create_default_config

    target = tmp_path / 'missing_config.json'
    assert not target.exists()
    cfg = load_and_validate_config(str(target))
    # Validate returned config matches shape of default
    default_cfg = create_default_config()
    assert cfg.keys() == default_cfg.keys()
    # Ensure wrapper captured write attempt
    assert recorded.get('path') == str(target)
    assert int(recorded.get('size', '0')) > 0


def test_emit_normalized_uses_safe_write(monkeypatch, tmp_path):
    # Prepare a minimally valid config matching schema required properties
    cfg_path = tmp_path / 'config.json'
    valid_cfg = {
        "version": "2.0",
        "application": "g6",
        "metrics": {"port": 9108, "host": "0.0.0.0"},
        "collection": {"interval_seconds": 60},
        "storage": {"csv_dir": "data/g6_data", "influx": {"enabled": False}},
        "indices": {"NIFTY": {"enable": True, "expiries": ["2025-11-14"], "strikes_otm": 10, "strikes_itm": 10}},
        "features": {"analytics_startup": False},
        "console": {"fancy_startup": False, "force_ascii": False, "live_panel": False, "runtime_status_file": "status.txt", "startup_banner": False}
    }
    import json
    cfg_path.write_text(json.dumps(valid_cfg), encoding='utf-8')
    monkeypatch.setenv('G6_CONFIG_EMIT_NORMALIZED', '1')
    from src.config.env_config import EnvConfig
    try:
        EnvConfig.clear_cache()
    except Exception:
        pass

    recorded: dict[str, str] = {}
    def recording(path, content, **kwargs):  # pragma: no cover
        recorded['path'] = str(path)
        recorded['size'] = str(len(content))
        return True
    monkeypatch.setattr('src.error_handling.safe_write_text', recording)

    from src.config.loader import load_and_validate_config, NORMALIZED_PATH
    load_and_validate_config(str(cfg_path))
    assert recorded.get('path') == str(NORMALIZED_PATH)
    assert int(recorded.get('size', '0')) > 0
