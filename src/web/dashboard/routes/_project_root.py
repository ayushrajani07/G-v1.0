from __future__ import annotations

from pathlib import Path

from src.config.env_config import EnvConfig


def resolve_project_root(core_project_root: callable) -> Path:
    """Resolve a project root with an env override.

    Order:
    - `G6_PROJECT_ROOT` env override if it exists on disk
    - `core_project_root()` (typically `src.web.dashboard.core.paths.project_root`)
    - Current working directory (best-effort)

    This helper exists so route modules can share the same behavior while still
    letting tests monkeypatch the core project_root callable.
    """

    try:
        env_root = EnvConfig.get_path("G6_PROJECT_ROOT", "").strip()
        if env_root:
            p = Path(env_root)
            if p.exists():
                return p
    except (AttributeError, TypeError, ValueError, OSError):
        pass

    try:
        return core_project_root()
    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        return Path.cwd()


__all__ = ["resolve_project_root"]
