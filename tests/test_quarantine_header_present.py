from pathlib import Path
import importlib

mod = importlib.import_module('scripts.ml.ensemble_consensus_exporter')


def test_ensemble_header_includes_quarantined(tmp_path, monkeypatch):
    from src.web.dashboard.core import paths as real_paths

    def fake_project_root():
        return tmp_path

    monkeypatch.setattr(real_paths, 'project_root', fake_project_root, raising=True)

    fp = mod.ensure_out_csv('NIFTY')
    header = fp.read_text(encoding='utf-8').splitlines()[0]
    fields = header.split(',')
    assert 'quarantined_models' in fields
