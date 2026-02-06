from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from typing import Any

try:
    from src.config.env_config import EnvConfig
except Exception:  # pragma: no cover
    EnvConfig = None  # type: ignore

# Prefer central env adapter if available (keeps behavior aligned with legacy output.py)
try:
    from src.collectors.env_adapter import get_bool as _env_get_bool
except Exception:  # pragma: no cover
    _env_get_bool = None  # type: ignore


def _get_env_bool(name: str, default: bool = False) -> bool:
    if EnvConfig is not None:
        try:
            return bool(EnvConfig.get_bool(name, default))
        except Exception:
            return default
    if _env_get_bool is not None:
        try:
            return bool(_env_get_bool(name, default))
        except Exception:
            return default
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return str(v).strip().lower() in {"1", "true", "yes", "on", "y"}
    except Exception:
        return default


def atomic_replace(src_path: str, dst_path: str, retries: int = 20, delay: float = 0.05) -> None:
    """Atomically replace dst with src, retrying on Windows file-lock errors.

    Test Fast Path:
      If env G6_TEST_FAST_IO=1 is set, drastically reduce retries & delay to
      avoid long stalls under CI / local Windows where pervasive file locking
      (AV / indexers) is not expected or acceptable for tests.
    """
    fast = _get_env_bool("G6_TEST_FAST_IO", False)
    if fast:
        # Keep a couple quick retries to tolerate a transient race but cap total wait ~<20ms.
        retries = min(retries, 3)
        delay = min(delay, 0.005)
    trace = fast and _get_env_bool("G6_TEST_FAST_IO_TRACE", False)

    for attempt in range(max(1, int(retries))):
        try:
            os.replace(src_path, dst_path)
            if trace:
                log = logging.getLogger(__name__)
                if log.hasHandlers():
                    log.debug("[fast-io] atomic_replace success attempt=%s dst=%s", attempt + 1, dst_path)
                else:
                    print(f"[fast-io] atomic_replace success attempt={attempt + 1} dst={dst_path}")
            return
        except (PermissionError, OSError) as e:  # noqa: PERF203
            if attempt + 1 >= retries:
                break
            if trace:
                log = logging.getLogger(__name__)
                if log.hasHandlers():
                    log.debug(
                        "[fast-io] atomic_replace retry attempt=%s err=%s dst=%s",
                        attempt + 1,
                        e,
                        dst_path,
                    )
                else:
                    print(f"[fast-io] atomic_replace retry attempt={attempt + 1} err={e} dst={dst_path}")
            time.sleep(delay)

    # Last attempt (raise if fails)
    os.replace(src_path, dst_path)


def atomic_write_json(
    dst_path: str,
    payload: dict[str, Any],
    *,
    ensure_ascii: bool = False,
    indent: int = 2,
    retries: int = 20,
    delay: float = 0.05,
) -> None:
    """Write JSON to a file atomically, with fsync and Windows-safe retry replace."""
    with contextlib.suppress(Exception):
        os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)

    fast = _get_env_bool("G6_TEST_FAST_IO", False)
    tmp = dst_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=ensure_ascii, default=str, indent=indent)
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                pass
    except Exception as e:
        try:
            from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler

            get_error_handler().handle_error(
                e,
                category=ErrorCategory.FILE_IO,
                severity=ErrorSeverity.LOW,
                component="output",
                function_name="atomic_write_json",
                message="atomic_write_json_failed",
                context={"path": dst_path},
            )
        except Exception:
            pass
        return

    # Propagate possibly reduced retries/delay in fast mode
    if fast:
        retries = min(retries, 3)
        delay = min(delay, 0.005)

    atomic_replace(tmp, dst_path, retries=retries, delay=delay)
