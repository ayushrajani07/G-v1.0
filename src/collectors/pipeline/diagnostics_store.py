"""Diagnostics store writer for per-expiry pipeline execution.

Writes one JSONL record per `ExpiryState` execution when enabled.
Design goals:
- Best-effort only: must never raise to callers.
- Minimal coupling: record is a plain dict, serialized with `default=str`.
"""

from __future__ import annotations

import os
import time
import json
from typing import Any

from .state import ExpiryState


def _serialize_error_records(state: ExpiryState) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in getattr(state, "error_records", []) or []:
        try:
            out.append(
                {
                    "phase": getattr(r, "phase", ""),
                    "classification": getattr(r, "classification", ""),
                    "message": getattr(r, "message", ""),
                    "detail": getattr(r, "detail", None),
                    "attempt": int(getattr(r, "attempt", 1) or 1),
                    "ts": float(getattr(r, "timestamp", 0.0) or 0.0),
                    "outcome_token": getattr(r, "outcome_token", ""),
                    "extra": getattr(r, "extra", None),
                }
            )
        except Exception:
            continue
    return out


def write_expiry_diagnostics(state: ExpiryState, *, path: str, schema_version: int = 1) -> bool:
    """Append a JSONL record for a single expiry pipeline execution.

    Returns:
        True if a record was written, False otherwise.
    """
    if not path:
        return False

    try:
        expiry_date = getattr(state, "expiry_date", None)
        expiry_iso = None
        try:
            if expiry_date is not None and hasattr(expiry_date, "isoformat"):
                expiry_iso = expiry_date.isoformat()  # type: ignore[union-attr]
        except Exception:
            expiry_iso = str(expiry_date)

        rec: dict[str, Any] = {
            "schema": int(schema_version),
            "exported_at": int(time.time()),
            "index": getattr(state, "index", ""),
            "rule": getattr(state, "rule", ""),
            "expiry_date": expiry_iso,
            "errors": list(getattr(state, "errors", []) or []),
            "error_records": _serialize_error_records(state),
            "meta": dict(getattr(state, "meta", {}) or {}),
        }

        # Ensure parent directory exists (if any)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        line = json.dumps(rec, ensure_ascii=False, default=str, separators=(",", ":"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except Exception:
        return False


__all__ = ["write_expiry_diagnostics"]
