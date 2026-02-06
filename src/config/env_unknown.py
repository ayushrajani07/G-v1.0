"""Unknown environment variable validation.

Purpose
-------
A recurring source of production drift is typos in env vars (e.g. `G6_METRICS_ENALBED`).
This module provides an optional startup check that can warn or fail-fast when
unknown `G6_*` variables are present.

The primary allowlist source is the repository's env dictionary (docs/env_dict.md).
That file supports both exact variables (e.g. `G6_METRICS_PORT`) and prefix entries
(e.g. `G6_ADAPTIVE_`) which permit any variable with that prefix.

Controls
--------
- `G6_WARN_ON_UNKNOWN_ENV_VARS=1`  -> log warnings
- `G6_FAIL_ON_UNKNOWN_ENV_VARS=1`  -> raise RuntimeError
- `G6_UNKNOWN_ENV_ALLOW`           -> CSV allowlist of exact names or prefixes
                                     using `*` suffix, e.g. `G6_FOO,G6_BAR_*,G6_BAZ*`

Defaults are non-breaking: no warnings and no failures unless enabled.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from src.config.env_config import EnvConfig
from src.config.env_lifecycle import ENV_LIFECYCLE_REGISTRY

logger = logging.getLogger(__name__)


def _parse_allow_items(raw: str) -> tuple[set[str], set[str]]:
    exact: set[str] = set()
    prefixes: set[str] = set()
    for item in [p.strip() for p in (raw or "").split(",") if p.strip()]:
        if item.endswith("*"):
            prefixes.add(item[:-1])
        else:
            exact.add(item)
    return exact, prefixes


@lru_cache(maxsize=1)
def load_known_g6_env_from_docs(doc_path: str | os.PathLike[str] = "docs/env_dict.md") -> tuple[set[str], set[str]]:
    """Load known env vars (exact + prefixes) from docs.

    Returns
    -------
    (exact, prefixes)
        - exact: set of exact env var names (e.g. `G6_METRICS_PORT`)
        - prefixes: set of prefixes that allow any env var starting with that prefix
                    (e.g. `G6_ADAPTIVE_`)
    """
    exact: set[str] = set()
    prefixes: set[str] = set()

    p = Path(doc_path)
    if not p.exists():
        return exact, prefixes

    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return exact, prefixes

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("G6_"):
            continue
        token = line.split(":", 1)[0].strip()
        if not token:
            continue
        if token.endswith("_"):
            prefixes.add(token)
        else:
            exact.add(token)

    # Always include lifecycle registry entries (defensive)
    try:
        for e in ENV_LIFECYCLE_REGISTRY:
            if e.name.startswith("G6_"):
                exact.add(e.name)
    except Exception:
        pass

    # These control vars are part of the validator itself.
    exact.update(
        {
            "G6_WARN_ON_UNKNOWN_ENV_VARS",
            "G6_FAIL_ON_UNKNOWN_ENV_VARS",
            "G6_UNKNOWN_ENV_ALLOW",
        }
    )

    return exact, prefixes


@lru_cache(maxsize=1)
def load_known_g6_env_from_code() -> set[str]:
    """Extract known env vars referenced in code.

    This is a pragmatic backstop so that the startup validator remains useful
    even if docs/env_dict.md isn't fully up-to-date.

    We only scan src/**/*.py (excluding archived/external dirs).
    This runs only when unknown-env validation is enabled, and is cached.
    """
    try:
        repo_root = Path(__file__).resolve().parents[2]
    except Exception:
        return set()

    src_root = repo_root / "src"
    if not src_root.exists():
        return set()

    token_re = re.compile(r"\bG6_[A-Z0-9_]+\b")
    out: set[str] = set()

    for p in src_root.rglob("*.py"):
        low = str(p).lower()
        if "\\.archived\\" in low or "/.archived/" in low:
            continue
        if "\\external\\" in low or "/external/" in low:
            continue
        if "\\.venv\\" in low or "/.venv/" in low:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        out.update(token_re.findall(text))

    return out


def find_unknown_g6_env_vars(
    environ: dict[str, str] | None = None,
    *,
    known_exact: Iterable[str] = (),
    known_prefixes: Iterable[str] = (),
    allow_exact: Iterable[str] = (),
    allow_prefixes: Iterable[str] = (),
) -> list[str]:
    env = environ or os.environ
    known_exact_set = set(known_exact)
    known_prefixes_set = set(known_prefixes)
    allow_exact_set = set(allow_exact)
    allow_prefixes_set = set(allow_prefixes)

    unknown: list[str] = []
    for k in env.keys():
        if not k.startswith("G6_"):
            continue
        if k in allow_exact_set:
            continue
        if k in known_exact_set:
            continue
        if any(k.startswith(pfx) for pfx in allow_prefixes_set):
            continue
        if any(k.startswith(pfx) for pfx in known_prefixes_set):
            continue
        unknown.append(k)

    unknown.sort()
    return unknown


def validate_unknown_env_vars(
    environ: dict[str, str] | None = None, *, strict_mode_override: bool | None = None
) -> None:
    """Optionally warn/fail on unknown G6_* env vars.

    This is designed to be called once at startup (e.g. orchestrator bootstrap).
    """
    try:
        warn_mode = EnvConfig.get_bool("G6_WARN_ON_UNKNOWN_ENV_VARS", False)
        strict_mode = EnvConfig.get_bool("G6_FAIL_ON_UNKNOWN_ENV_VARS", False)
        if strict_mode_override is not None:
            strict_mode = strict_mode_override

        if not warn_mode and not strict_mode:
            return

        known_exact, known_prefixes = load_known_g6_env_from_docs()
        try:
            known_exact = set(known_exact)
            known_exact.update(load_known_g6_env_from_code())
        except Exception:
            pass

        raw_allow = EnvConfig.get_str("G6_UNKNOWN_ENV_ALLOW", "")
        allow_exact, allow_prefixes = _parse_allow_items(raw_allow)

        unknown = find_unknown_g6_env_vars(
            environ or os.environ,
            known_exact=known_exact,
            known_prefixes=known_prefixes,
            allow_exact=allow_exact,
            allow_prefixes=allow_prefixes,
        )
        if not unknown:
            return

        msg = (
            "Unknown G6_* environment variables detected: "
            + ", ".join(unknown)
            + ". (Set G6_UNKNOWN_ENV_ALLOW to ignore specific keys.)"
        )

        if strict_mode:
            logger.error(msg)
            raise RuntimeError(msg)
        if warn_mode:
            logger.warning(msg)
    except RuntimeError:
        raise
    except Exception:
        # Never crash startup unless strict mode requested.
        logger.debug("Unknown env var validation failed", exc_info=True)


__all__ = [
    "find_unknown_g6_env_vars",
    "load_known_g6_env_from_docs",
    "validate_unknown_env_vars",
]
