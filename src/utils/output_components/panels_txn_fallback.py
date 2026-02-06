from __future__ import annotations

import json
import os
import shutil as _sh
import time as _t


def fallback_copy_and_cleanup_after_commit(
    base_dir: str,
    *,
    txn_id: str,
    committed_at: str,
) -> None:
    """Best-effort rescue when a panels transaction commit fails silently.

    Mirrors legacy behavior from src.utils.output.OutputRouter.PanelsTransaction.__exit__:
    - If staging dir exists, copy staged *.json into base_dir
    - Write .meta.json only if it doesn't exist
    - Aggressively cleanup staging dir and prune base_dir/.txn if empty

    All operations are best-effort and must never raise.
    """

    try:
        stage_dir = os.path.join(base_dir, ".txn", txn_id)
        if not os.path.isdir(stage_dir):
            return

        for name in os.listdir(stage_dir):
            if name.endswith(".json"):
                src = os.path.join(stage_dir, name)
                dst = os.path.join(base_dir, name)
                try:
                    os.makedirs(base_dir, exist_ok=True)
                    _sh.copyfile(src, dst)
                except Exception:
                    try:
                        with open(src, "rb") as _rf, open(dst, "wb") as _wf:
                            _sh.copyfileobj(_rf, _wf, length=1024 * 1024)
                    except Exception:
                        pass

        try:
            meta_path = os.path.join(base_dir, ".meta.json")
            if not os.path.exists(meta_path):
                _panels = [p[:-5] for p in os.listdir(stage_dir) if p.endswith(".json")]
                meta_payload = {
                    "last_txn_id": txn_id,
                    "committed_at": committed_at,
                    "panels": _panels,
                }
                try:
                    with open(meta_path, "w", encoding="utf-8") as _mf:
                        json.dump(meta_payload, _mf)
                except Exception as me:
                    try:
                        from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler

                        get_error_handler().handle_error(
                            me,
                            category=ErrorCategory.FILE_IO,
                            severity=ErrorSeverity.LOW,
                            component="output",
                            function_name="PanelsTransaction.__exit__",
                            message="panel_meta_write_failed",
                            context={"path": meta_path},
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            _sh.rmtree(stage_dir, ignore_errors=True)
            if os.path.isdir(stage_dir):
                _t.sleep(0.05)
                _sh.rmtree(stage_dir, ignore_errors=True)

            root_dir = os.path.join(base_dir, ".txn")
            if os.path.isdir(root_dir) and not os.listdir(root_dir):
                _sh.rmtree(root_dir, ignore_errors=True)
        except Exception:
            pass
    except Exception:
        pass


def fallback_cleanup_after_abort(base_dir: str, *, txn_id: str) -> None:
    """Best-effort cleanup on abort if staging directory persists."""

    try:
        stage_dir = os.path.join(base_dir, ".txn", txn_id)
        if os.path.isdir(stage_dir):
            _sh.rmtree(stage_dir, ignore_errors=True)
            if os.path.isdir(stage_dir):
                _t.sleep(0.05)
                _sh.rmtree(stage_dir, ignore_errors=True)

        root_dir = os.path.join(base_dir, ".txn")
        if os.path.isdir(root_dir) and not os.listdir(root_dir):
            _sh.rmtree(root_dir, ignore_errors=True)
    except Exception:
        pass
