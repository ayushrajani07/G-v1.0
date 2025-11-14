from pathlib import Path

import importlib
import sys

# Import exporter module
mod = importlib.import_module('scripts.ml.ensemble_consensus_exporter')


def test_ensure_out_csv_writes_header(tmp_path: Path, monkeypatch):
    # Patch project_root to a temp dir
    # The exporter imports project_root() from src.web.dashboard.core.paths
    # We'll monkeypatch that function in the imported module's namespace indirectly by
    # adding a fake package with the same interface to sys.modules.

    # However, easier: monkeypatch the project_root function attribute used in the module
    # by editing sys.modules for the target path provider
    from src.web.dashboard.core import paths as real_paths

    def fake_project_root():
        return tmp_path

    monkeypatch.setattr(real_paths, 'project_root', fake_project_root, raising=True)

    # Ensure directory clean
    out = mod.ensure_out_csv('ZZZTEST')
    assert out.exists()
    content = out.read_text(encoding='utf-8')
    first_line = content.splitlines()[0] if content else ''
    assert first_line.strip() == 'timestamp,consensus,disagreement,models_count,models,index,horizon'

    # calling again should not duplicate header
    out2 = mod.ensure_out_csv('ZZZTEST')
    assert out2 == out
    content2 = out2.read_text(encoding='utf-8')
    lines = content2.splitlines()
    assert lines.count('timestamp,consensus,disagreement,models_count,models,index,horizon') == 1
