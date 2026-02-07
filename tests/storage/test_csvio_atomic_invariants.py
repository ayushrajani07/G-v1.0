import csv
from pathlib import Path

from src.config.env_config import EnvConfig
from src.storage.csv_writer import CsvWriter


def _read_rows(path: Path) -> list[list[str]]:
    with path.open('r', encoding='utf-8', newline='') as f:
        return list(csv.reader(f))


def test_csvio_atomic_aligns_rows_when_header_changes(tmp_path: Path, monkeypatch) -> None:
    # Force CSVIO to use the atomic backend for alignment semantics.
    monkeypatch.setenv('G6_CSVIO_BACKEND', 'atomic')
    EnvConfig.clear_cache()

    writer = CsvWriter(base_dir=str(tmp_path))
    rel = 'aligned.csv'
    fp = tmp_path / rel

    header_v1 = ['timestamp', 'strike', 'offset', 'atm']
    writer.append_row(rel, ['t1', 110, 10, 100], header_v1)

    # Simulate schema evolution where caller no longer provides 'atm'.
    header_v2 = ['timestamp', 'strike', 'offset']
    writer.append_row(rel, ['t2', 120, 20], header_v2)

    assert fp.exists()
    rows = _read_rows(fp)

    assert rows[0] == header_v1
    assert len(rows) == 3

    # Second data row must be aligned to file header and derive atm = strike - offset.
    assert rows[2][0] == 't2'
    assert float(rows[2][1]) == 120.0
    assert int(float(rows[2][2])) == 20
    assert float(rows[2][3]) == 100.0
