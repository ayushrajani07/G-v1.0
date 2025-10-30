"""
Legacy entrypoint shim for summary view.

This module exists for backward compatibility and will be removed in a future release.
On import, it emits a DeprecationWarning and re-exports main() forwarding to scripts.summary.app.
"""
from __future__ import annotations

import sys
import warnings

warnings.warn(
    "scripts.summary_view is deprecated; use scripts.summary.app instead.",
    DeprecationWarning,
    stacklevel=2,
)

try:
    from scripts.summary.app import run as _run  # type: ignore
except Exception as _e:  # pragma: no cover
    def _run(argv=None):
        return 1


def main(argv=None):
    return _run(argv or sys.argv[1:])

__all__ = ["main"]
