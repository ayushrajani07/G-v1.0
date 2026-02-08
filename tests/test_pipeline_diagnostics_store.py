from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.config.env_config import EnvConfig


class Ctx:
    providers: Any = None


def test_pipeline_diagnostics_store_writes_jsonl(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "diag" / "pipeline.jsonl"
    monkeypatch.setenv("G6_PIPELINE_DIAGNOSTICS_STORE_PATH", str(p))
    monkeypatch.setenv("G6_PIPELINE_INCLUDE_DIAGNOSTICS", "1")
    EnvConfig.clear_cache()

    st = ExpiryState(index="NIFTY", rule="weekly", settings=object())

    def a(_c, s):
        s.meta["a"] = 1
        return s

    out = execute_phases(Ctx(), st, [a])
    assert out is not None

    assert p.exists(), "expected diagnostics store file"
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    rec = json.loads(lines[0])
    assert rec["schema"] == 1
    assert rec["index"] == "NIFTY"
    assert rec["rule"] == "weekly"
    assert "meta" in rec
    assert "pipeline_summary" in rec["meta"]
    assert "phase_runs" in rec["meta"]
