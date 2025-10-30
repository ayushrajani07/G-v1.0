from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Return the repository root given a file location within src/web/dashboard.

    app.py -> dashboard -> web -> src -> PROJECT ROOT
    """
    return Path(__file__).resolve().parents[4]
