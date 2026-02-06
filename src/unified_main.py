"""unified_main (REMOVED)
==========================

Fully removed on 2025-09-28 (orchestrator convergence).
All legacy implementation stripped. Any import now raises RuntimeError.

Use instead (CLI):
    python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60

Programmatic APIs:
    from src.orchestrator.bootstrap import bootstrap_runtime
    from src.orchestrator.loop import run_loop
    from src.orchestrator.cycle import run_cycle

Legacy loop flags were removed; refer to DEPRECATIONS.md for historical notes.
"""
from __future__ import annotations

_REMOVAL_MESSAGE = (
    "unified_main removed. Use scripts/run_orchestrator_loop.py or orchestrator modules. "
    "Remove legacy loop flags. See DEPRECATIONS.md."
)

def __getattr__(name: str):  # pragma: no cover
    raise RuntimeError(_REMOVAL_MESSAGE)

# Import side-effect: raise immediately
raise RuntimeError(_REMOVAL_MESSAGE)
