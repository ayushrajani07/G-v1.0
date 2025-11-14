"""Lightweight .env file loader for the G6 Platform.

Goals:
  * Zero external dependency (no python-dotenv) – simple parser sufficient.
  * Deterministic precedence: .env.local > .env (first wins) unless override=True.
  * Opt-out via env flag G6_NO_ENV_FILE=1.
  * Idempotent (safe to call multiple times).
  * Does not overwrite already-set OS env vars unless override=True.

Security:
  * Secrets SHOULD live in an untracked .env.local or an external secret manager.
  * The committed .env.example MUST NOT contain real credentials.

Usage:
    from src.config.env_loader import ensure_loaded
    ensure_loaded()  # loads if not already loaded

    # Explicit call with custom paths
    from src.config.env_loader import load_env
    load_env(["/secure/location/.env.local", ".env"], override=False, verbose=True)

Environment Flags:
    G6_NO_ENV_FILE=1  -> Skip loading any .env files (e.g., container already sets vars)
    G6_ENV_FILE_VERBOSE=1 -> Verbose logging of each applied key

Parser Notes:
  * Supports KEY=VALUE, strips surrounding single/double quotes.
  * Ignores blank lines and lines beginning with '#'.
  * Allows inline comments after value if preceded by at least one space: KEY=123  # comment
  * Basic ${VAR} expansion (recursive limited to one pass to avoid cycles).
"""
from __future__ import annotations

from pathlib import Path
import os
import re
from typing import Sequence
import logging

logger = logging.getLogger(__name__)

_ENV_LOADED = False

_VAR_REF_RE = re.compile(r"\${([^}]+)}")


def _expand(value: str) -> str:
    """Expand ${VAR} patterns using current environment (single pass)."""
    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        return os.environ.get(name, "")
    return _VAR_REF_RE.sub(repl, value)


def _parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # Allow inline comments: KEY=VALUE  # comment
    if "#" in line:
        hash_index = line.find("#")
        before = line[:hash_index]
        # treat as inline comment only if whitespace precedes '#'
        if before.endswith(" ") or before.endswith("\t"):
            line = before.rstrip()
    if "=" not in line:
        return None
    key, raw_val = line.split("=", 1)
    key = key.strip()
    val = raw_val.strip()
    # Strip surrounding quotes
    if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
        val = val[1:-1]
    val = _expand(val)
    return key, val


def load_env(paths: Sequence[str] | None = None, *, override: bool = False, verbose: bool | None = None) -> int:
    """Load environment variables from given file paths.

    Args:
        paths: Ordered list of file paths. First found path is read, then next, etc.
                Default order: [".env.local", ".env"].
        override: If True, overwrite existing os.environ values.
        verbose: If True (or G6_ENV_FILE_VERBOSE=1), print applied keys to stdout.

    Returns:
        Count of variables set/updated.
    """
    if os.environ.get("G6_NO_ENV_FILE", "0") == "1":
        return 0
    if paths is None:
        paths = [".env.local", ".env"]
    if verbose is None:
        verbose = os.environ.get("G6_ENV_FILE_VERBOSE", "0") == "1"
    applied = 0
    # Search in CWD and repository root (src/config/../../)
    search_dirs: list[Path] = [Path.cwd()]
    try:
        repo_root = Path(__file__).resolve().parents[2]
        if repo_root not in search_dirs:
            search_dirs.append(repo_root)
    except Exception:
        pass

    for p in paths:
        found_any = False
        for base in search_dirs:
            fp = (base / p).resolve()
            if not fp.exists():
                continue
            found_any = True
            try:
                for raw in fp.read_text(encoding="utf-8").splitlines():
                    parsed = _parse_line(raw)
                    if not parsed:
                        continue
                    k, v = parsed
                    if not override and k in os.environ:
                        continue
                    os.environ[k] = v
                    applied += 1
                    if verbose:
                        try:
                            red = '*redacted*' if any(s in k for s in ('KEY','SECRET','TOKEN','PASS')) else v
                            logger.info("[env_loader] set %s=%s", k, red)
                        except Exception:
                            pass
            except Exception as e:  # pragma: no cover - defensive
                try:
                    logger.warning("[env_loader] warning: failed reading %s: %s", fp, e)
                except Exception:
                    pass
        # proceed to next filename; later files may add keys
    return applied


def ensure_loaded() -> None:
    """Idempotent loader invoked at package import boundaries."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    load_env()
    _ENV_LOADED = True


__all__ = ["load_env", "ensure_loaded"]
