from __future__ import annotations

from collections.abc import Iterable
import contextlib
import datetime as _dt
import json
import logging
import os
from pathlib import Path
import shutil as _sh
import time as _t
from typing import Any, cast

from src.metrics.protocols import CounterLike
from src.utils.csv_cache import read_json_cached

from .atomic import atomic_replace
from .events import OutputEvent

try:
    # Prefer central env adapter for consistency
    from src.collectors.env_adapter import (
        get_bool as _env_get_bool,
        get_str as _env_get_str,  # type: ignore
    )
except Exception:  # pragma: no cover

    def _env_get_str(name: str, default: str = "") -> str:
        try:
            v = os.getenv(name)
            return default if v is None else v
        except Exception:
            return default

    def _env_get_bool(name: str, default: bool = False) -> bool:
        try:
            v = os.getenv(name)
            if v is None:
                return default
            return v.strip().lower() in {"1", "true", "yes", "on", "y"}
        except Exception:
            return default


def is_truthy_env(name: str) -> bool:
    return _env_get_bool(name, False)


# Optional imports for late import elimination
try:
    from src.health import runtime as health_runtime
except ImportError:
    health_runtime = None  # type: ignore
try:
    from src.health.models import HealthLevel, HealthState
except ImportError:
    HealthLevel = None  # type: ignore
    HealthState = None  # type: ignore
try:
    from src.metrics import get_metrics_singleton
except ImportError:
    get_metrics_singleton = None  # type: ignore
try:
    from src.panels.version import PANEL_SCHEMA_VERSION
except ImportError:
    PANEL_SCHEMA_VERSION = None  # type: ignore


class PanelFileSink:
    """Writes per-panel JSON files for the summarizer to consume later.

    Enabled by adding 'panels' to G6_OUTPUT_SINKS.
    Config:
      - G6_PANELS_DIR: base directory to write panel files (default: data/panels)
      - G6_PANELS_INCLUDE: CSV of panel names to include (upper/lower ignored). If empty => allow all.
      - G6_PANELS_ATOMIC: true/false, atomic replace writes (default true)
    Usage via router.panel_update(panel, data, kind=optional)
    """

    def __init__(self, base_dir: str, include: Iterable[str] | None = None, atomic: bool = True) -> None:
        self._base_dir = base_dir
        self._include = {s.strip().lower() for s in include} if include else None
        self._atomic = bool(atomic)
        # Control meta emission (default on)
        self._always_meta = _env_get_bool("G6_PANELS_ALWAYS_META", True)
        # Optional schema wrapper gate (v1 wrapper adds version + emitted_at and nests legacy payload under 'panel')
        self._schema_wrapper = _env_get_bool("G6_PANELS_SCHEMA_WRAPPER", False)
        # Transaction staging directory (per-txn subfolders)
        self._txn_root = os.path.join(self._base_dir, ".txn")
        # Ensure base dir exists early to make commit meta writes reliable
        with contextlib.suppress(Exception):
            os.makedirs(self._base_dir, exist_ok=True)

    def _mark_health(self, ok: bool) -> None:
        """Optional graded health for panels file sink (env-gated)."""
        try:
            if not is_truthy_env("G6_HEALTH_COMPONENTS"):
                return
            if not health_runtime or not HealthLevel or not HealthState:
                return
            if ok:
                health_runtime.set_component("panels_sink", HealthLevel.HEALTHY, HealthState.HEALTHY)
            else:
                health_runtime.set_component("panels_sink", HealthLevel.WARNING, HealthState.WARNING)
        except Exception:
            pass

    def close(self) -> None:  # pragma: no cover
        try:
            if os.path.isdir(self._txn_root) and not os.listdir(self._txn_root):
                _sh.rmtree(self._txn_root, ignore_errors=True)
        except Exception:
            pass

    def _allowed(self, panel: str) -> bool:
        return True if self._include is None else (panel.lower() in self._include)

    @staticmethod
    def _atomic_replace(src_path: str, dst_path: str, retries: int = 20, delay: float = 0.05) -> None:
        atomic_replace(src_path, dst_path, retries=retries, delay=delay)

    def _write_json_atomic(self, dst: str, payload: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                try:
                    pretty = _env_get_bool("G6_PANELS_PRETTY_JSON", True)
                except Exception:
                    pretty = True
                if pretty:
                    json.dump(payload, f, ensure_ascii=False, default=str, indent=2)
                else:
                    json.dump(payload, f, ensure_ascii=False, default=str, separators=(",", ":"))
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
                    function_name="PanelFileSink._write_json_atomic",
                    message="panel_json_write_failed",
                    context={"path": dst},
                )
            except Exception:
                pass
            return
        if self._atomic:
            self._atomic_replace(tmp, dst)
        else:
            os.replace(tmp, dst)

    def _txn_dir(self, txn_id: str) -> str:
        return os.path.join(self._txn_root, str(txn_id))

    def _txn_dst(self, txn_id: str, panel_s: str) -> str:
        return os.path.join(self._txn_dir(txn_id), f"{panel_s}.json")

    def emit(self, event: OutputEvent) -> None:
        extra = event.extra or {}
        txn_id = None
        txn_action = None
        try:
            if isinstance(extra, dict):
                txn_id = extra.get("_txn_id")
                txn_action = extra.get("_txn_action")
        except Exception:
            txn_id = None
            txn_action = None

        if txn_action in ("commit", "abort") and txn_id:
            try:
                if txn_action == "commit":
                    stage_dir = self._txn_dir(str(txn_id))
                    committed: list[str] = []
                    diag_env = _env_get_str("G6_PANELS_TXN_DEBUG", "")
                    if (
                        not diag_env
                        and _env_get_str("PYTEST_CURRENT_TEST", "")
                        and is_truthy_env("G6_PANELS_TXN_AUTO_DEBUG")
                    ):
                        diag_env = "1"
                    diag = diag_env not in ("", "0", "false", "no", "off")
                    if diag:
                        try:
                            _present = os.path.isdir(stage_dir)
                            _contents = os.listdir(stage_dir) if _present else "NA"
                            _log = logging.getLogger(__name__)
                            if _log.hasHandlers():
                                _log.debug(
                                    "[panels-txn-debug] commit_start id=%s stage_dir=%s present=%s contents=%s",
                                    txn_id,
                                    stage_dir,
                                    _present,
                                    _contents,
                                )
                            else:
                                print(
                                    f"[panels-txn-debug] commit_start id={txn_id} "
                                    f"stage_dir={stage_dir} present={_present} contents={_contents}"
                                )
                        except Exception:
                            pass

                    if os.path.isdir(stage_dir):
                        for name in list(os.listdir(stage_dir)):
                            if not name.endswith(".json"):
                                continue
                            src = os.path.join(stage_dir, name)
                            dst = os.path.join(self._base_dir, name)
                            with contextlib.suppress(Exception):
                                os.makedirs(self._base_dir, exist_ok=True)
                            try:
                                try:
                                    _sh.copyfile(src, dst + ".tmpcopy")
                                except Exception:
                                    try:
                                        with open(src, "rb") as _rf, open(dst + ".tmpcopy", "wb") as _wf:
                                            _sh.copyfileobj(_rf, _wf, length=1024 * 1024)
                                    except Exception:
                                        with open(src, "rb") as _rf, open(dst + ".tmpcopy", "wb") as _wf:
                                            _wf.write(_rf.read())

                                try:
                                    if os.path.exists(dst):
                                        os.remove(dst)
                                except Exception:
                                    pass

                                try:
                                    os.replace(dst + ".tmpcopy", dst)
                                except Exception:
                                    with contextlib.suppress(Exception):
                                        _sh.copyfile(src, dst)

                                committed.append(name[:-5])
                            except Exception:
                                try:
                                    if os.path.exists(dst + ".tmpcopy"):
                                        os.remove(dst + ".tmpcopy")
                                except Exception:
                                    pass
                    else:
                        if is_truthy_env("G6_PANELS_TXN_DEBUG"):
                            _log = logging.getLogger(__name__)
                            if _log.hasHandlers():
                                _log.debug(
                                    "[panels-txn-debug] commit stage_dir_missing id=%s dir=%s",
                                    txn_id,
                                    stage_dir,
                                )
                            else:
                                print(
                                    f"[panels-txn-debug] commit stage_dir_missing id={txn_id} dir={stage_dir}"
                                )

                    if not committed and os.path.isdir(stage_dir):
                        try:
                            for name in os.listdir(stage_dir):
                                if not name.endswith(".json"):
                                    continue
                                src = os.path.join(stage_dir, name)
                                dst = os.path.join(self._base_dir, name)
                                try:
                                    _sh.copyfile(src, dst)
                                    committed.append(name[:-5])
                                except Exception:
                                    try:
                                        with open(src, "rb") as _rf, open(dst, "wb") as _wf:
                                            _sh.copyfileobj(_rf, _wf, length=1024 * 1024)
                                        committed.append(name[:-5])
                                    except Exception:
                                        pass
                        except Exception:
                            pass

                    try:
                        if os.path.isdir(stage_dir):
                            for name in os.listdir(stage_dir):
                                if not name.endswith(".json"):
                                    continue
                                dst = os.path.join(self._base_dir, name)
                                if not os.path.exists(dst):
                                    src = os.path.join(stage_dir, name)
                                    try:
                                        _sh.copyfile(src, dst)
                                        if name[:-5] not in committed:
                                            committed.append(name[:-5])
                                        if diag:
                                            _log = logging.getLogger(__name__)
                                            if _log.hasHandlers():
                                                _log.debug(
                                                    "[panels-txn-debug] final_rescue_copied name=%s id=%s",
                                                    name,
                                                    txn_id,
                                                )
                                            else:
                                                print(
                                                    f"[panels-txn-debug] final_rescue_copied name={name} "
                                                    f"id={txn_id}"
                                                )
                                    except Exception:
                                        try:
                                            with open(src, "rb") as _rf, open(dst, "wb") as _wf:
                                                _sh.copyfileobj(_rf, _wf, length=1024 * 1024)
                                            if name[:-5] not in committed:
                                                committed.append(name[:-5])
                                            if diag:
                                                _log = logging.getLogger(__name__)
                                                if _log.hasHandlers():
                                                    _log.debug(
                                                        "[panels-txn-debug] final_rescue_copied name=%s id=%s",
                                                        name,
                                                        txn_id,
                                                    )
                                                else:
                                                    print(
                                                        f"[panels-txn-debug] final_rescue_copied name={name} "
                                                        f"id={txn_id}"
                                                    )
                                        except Exception:
                                            if diag:
                                                _log = logging.getLogger(__name__)
                                                if _log.hasHandlers():
                                                    _log.debug(
                                                        "[panels-txn-debug] final_rescue_failed name=%s id=%s",
                                                        name,
                                                        txn_id,
                                                    )
                                                else:
                                                    print(
                                                        f"[panels-txn-debug] final_rescue_failed name={name} "
                                                        f"id={txn_id}"
                                                    )
                                            pass
                    except Exception:
                        pass

                    if diag:
                        try:
                            _base_contents = os.listdir(self._base_dir) if os.path.isdir(self._base_dir) else "NA"
                            _log = logging.getLogger(__name__)
                            if _log.hasHandlers():
                                _log.debug(
                                    "[panels-txn-debug] commit_end id=%s committed=%s base_contents=%s",
                                    txn_id,
                                    committed,
                                    _base_contents,
                                )
                            else:
                                print(
                                    f"[panels-txn-debug] commit_end id={txn_id} committed={committed} "
                                    f"base_contents={_base_contents}"
                                )
                        except Exception:
                            pass

                    if self._always_meta:
                        try:
                            meta_path = os.path.join(self._base_dir, ".meta.json")
                            meta_payload = {
                                "last_txn_id": str(txn_id),
                                "committed_at": event.timestamp,
                                "panels": committed,
                            }
                            self._write_json_atomic(meta_path, meta_payload)
                        except Exception:
                            pass

                    try:
                        if os.path.isdir(self._txn_dir(str(txn_id))):
                            _sh.rmtree(self._txn_dir(str(txn_id)), ignore_errors=True)
                            if os.path.isdir(self._txn_dir(str(txn_id))):
                                _t.sleep(0.05)
                                with contextlib.suppress(Exception):
                                    _sh.rmtree(self._txn_dir(str(txn_id)), ignore_errors=True)
                        try:
                            if os.path.isdir(self._txn_root) and not os.listdir(self._txn_root):
                                _sh.rmtree(self._txn_root, ignore_errors=True)
                        except Exception:
                            pass
                    except Exception:
                        pass

                    self._mark_health(True)
                    try:
                        if get_metrics_singleton:
                            m = get_metrics_singleton()
                            if m:
                                h = getattr(m, "panels_txn_commits", None)
                                if h is not None:
                                    cast(CounterLike, h).inc()
                    except Exception:
                        pass
                else:
                    diag = is_truthy_env("G6_PANELS_TXN_DEBUG")
                    if diag:
                        try:
                            _txn_path = self._txn_dir(str(txn_id))
                            _exists = os.path.isdir(_txn_path)
                            print(
                                f"[panels-txn-debug] abort_start id={txn_id} path={_txn_path} exists={_exists}"
                            )
                        except Exception:
                            pass
                    try:
                        txn_path = self._txn_dir(str(txn_id))
                        _sh.rmtree(txn_path, ignore_errors=True)
                        if os.path.isdir(txn_path):
                            for _i in range(3):
                                _t.sleep(0.02 * (2**_i))
                                if not os.path.isdir(txn_path):
                                    break
                                _sh.rmtree(txn_path, ignore_errors=True)
                        try:
                            if os.path.isdir(self._txn_root) and not os.listdir(self._txn_root):
                                _sh.rmtree(self._txn_root, ignore_errors=True)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    if diag:
                        try:
                            _txn_exists = os.path.isdir(self._txn_dir(str(txn_id)))
                            _root_exists = os.path.isdir(self._txn_root)
                            _root_contents = os.listdir(self._txn_root) if _root_exists else "NA"
                            print(
                                f"[panels-txn-debug] abort_end id={txn_id} txn_exists={_txn_exists} "
                                f"root_exists={_root_exists} root_contents={_root_contents}"
                            )
                        except Exception:
                            pass
                    self._mark_health(False)
                    try:
                        if get_metrics_singleton:
                            m = get_metrics_singleton()
                            if m:
                                h = getattr(m, "panels_txn_aborts", None)
                                if h is not None:
                                    cast(CounterLike, h).inc()
                    except Exception:
                        pass
                return
            except Exception as e:
                try:
                    if txn_action == "commit":
                        stage_dir = self._txn_dir(str(txn_id))
                        if os.path.isdir(stage_dir):
                            for name in os.listdir(stage_dir):
                                if not name.endswith(".json"):
                                    continue
                                src = os.path.join(stage_dir, name)
                                dst = os.path.join(self._base_dir, name)
                                try:
                                    os.makedirs(self._base_dir, exist_ok=True)
                                    _sh.copyfile(src, dst)
                                except Exception:
                                    try:
                                        with open(src, "rb") as _rf, open(dst, "wb") as _wf:
                                            _sh.copyfileobj(_rf, _wf, length=1024 * 1024)
                                    except Exception:
                                        pass
                            if self._always_meta:
                                try:
                                    meta_path = os.path.join(self._base_dir, ".meta.json")
                                    meta_payload = {
                                        "last_txn_id": str(txn_id),
                                        "committed_at": event.timestamp,
                                        "panels": [],
                                    }
                                    self._write_json_atomic(meta_path, meta_payload)
                                except Exception:
                                    pass
                            with contextlib.suppress(Exception):
                                _sh.rmtree(stage_dir, ignore_errors=True)
                except Exception:
                    pass
                if is_truthy_env("G6_PANELS_TXN_DEBUG"):
                    with contextlib.suppress(Exception):
                        print(f"[panels-txn-debug] commit_exception id={txn_id} err={e}")
                return

        panel = extra.get("_panel") if isinstance(extra, dict) else None
        if not panel:
            return
        panel_s = str(panel)
        if not self._allowed(panel_s):
            return
        mode = str(extra.get("_mode") or "update").lower()
        cap = extra.get("_cap")
        try:
            cap_n = int(cap) if cap is not None else None
        except Exception:
            cap_n = None

        in_txn = bool(txn_id)
        if in_txn:
            dst = self._txn_dst(str(txn_id), panel_s)
        else:
            with contextlib.suppress(Exception):
                os.makedirs(self._base_dir, exist_ok=True)
            dst = os.path.join(self._base_dir, f"{panel_s}.json")

        try:
            prev_data = None
            if mode in ("append", "extend"):
                if os.path.exists(dst):
                    try:
                        prev_obj = read_json_cached(Path(dst))
                        if isinstance(prev_obj, dict):
                            if "data" in prev_obj:
                                prev_data = prev_obj.get("data")
                            elif "panel" in prev_obj and isinstance(prev_obj.get("panel"), dict):
                                prev_data = prev_obj["panel"].get("data")  # type: ignore[index]
                    except Exception:
                        prev_data = None

                if prev_data is None and in_txn:
                    live = os.path.join(self._base_dir, f"{panel_s}.json")
                    if os.path.exists(live):
                        try:
                            prev_obj2 = read_json_cached(Path(live))
                            if isinstance(prev_obj2, dict):
                                if "data" in prev_obj2:
                                    prev_data = prev_obj2.get("data")
                                elif "panel" in prev_obj2 and isinstance(prev_obj2.get("panel"), dict):
                                    prev_data = prev_obj2["panel"].get("data")  # type: ignore[index]
                        except Exception:
                            prev_data = None

            new_data = event.data
            if mode == "append":
                items = []
                if isinstance(prev_data, list):
                    items = list(prev_data)
                elif isinstance(prev_data, dict):
                    prev_items = prev_data.get("items")
                    if isinstance(prev_items, list):
                        items = list(prev_items)
                items.append(new_data)
                if cap_n is not None and cap_n > 0:
                    items = items[-cap_n:]
                new_data = items
            elif mode == "extend":
                items = []
                if isinstance(prev_data, list):
                    items = list(prev_data)
                elif isinstance(prev_data, dict):
                    prev_items = prev_data.get("items")
                    if isinstance(prev_items, list):
                        items = list(prev_items)
                if isinstance(new_data, list):
                    items.extend(new_data)
                else:
                    items.append(new_data)
                if cap_n is not None and cap_n > 0:
                    items = items[-cap_n:]
                new_data = items

            legacy_payload = {
                "panel": panel_s,
                "updated_at": event.timestamp,
                "kind": extra.get("_kind"),
                "data": new_data,
            }
            if self._schema_wrapper:
                try:
                    ts_val = event.timestamp
                    if isinstance(ts_val, str):
                        try:
                            ts_val = float(ts_val)
                        except Exception:
                            ts_val = None
                    if isinstance(ts_val, (int, float)):
                        iso_ts = (
                            _dt.datetime.fromtimestamp(float(ts_val), _dt.UTC)
                            .isoformat()
                            .replace("+00:00", "Z")
                        )
                    else:
                        iso_ts = None
                except Exception:
                    iso_ts = None
                _PANEL_SCHEMA_VERSION = PANEL_SCHEMA_VERSION if PANEL_SCHEMA_VERSION else 1
                payload = {
                    "version": _PANEL_SCHEMA_VERSION,
                    "schema_version": _PANEL_SCHEMA_VERSION,
                    "emitted_at": iso_ts or event.timestamp,
                    "panel": legacy_payload,
                }
            else:
                payload = legacy_payload

            self._write_json_atomic(dst, payload)
            self._mark_health(True)
            try:
                if get_metrics_singleton:
                    m = get_metrics_singleton()
                    if m:
                        h_writes = getattr(m, "panels_writes", None)
                        if h_writes is not None:
                            cast(CounterLike, h_writes).inc()
                        h_updates = getattr(m, "panels_updates_total", None)
                        if h_updates is not None:
                            with contextlib.suppress(Exception):
                                cast(CounterLike, h_updates).labels(mode=mode).inc()
            except Exception:
                pass
        except Exception:
            self._mark_health(False)
            try:
                if get_metrics_singleton:
                    m = get_metrics_singleton()
                    if m:
                        h_err = getattr(m, "panels_write_errors", None)
                        if h_err is not None:
                            cast(CounterLike, h_err).inc()
            except Exception:
                pass
