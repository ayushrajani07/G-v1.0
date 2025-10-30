#!/usr/bin/env python3
"""
Patch Grafana dashboards to use a specific datasource name (default: "G6 Prometheus").

Usage:
  python scripts/tools/grafana_ds_patch.py [ROOT] [--ds-name "G6 Prometheus"] [--dry-run]

- ROOT: Project root to scan (defaults to current working directory)
- --ds-name: Datasource name to set on panels/targets/templating (default: "G6 Prometheus")
- --dry-run: Print changes but do not write files

The script searches common dashboard locations and any '*.json' files containing Grafana dashboard structures.
It attempts to patch the following locations:
- panel.datasource
- panel.targets[*].datasource
- templating.list[*].datasource

It supports both legacy string datasource values and the newer object form (e.g., {"type":"prometheus","uid":"..."}).
In all cases, it replaces the value with the provided datasource name string and removes any uid fields when found.

Backups: For each modified file, a single backup copy with suffix ".bak" is created if not already present.
"""
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

DEFAULT_DS_NAME = "G6 Prometheus"

COMMON_DASHBOARD_DIRS = (
    "provisioning/dashboards",
    "dashboards",
    "grafana/dashboards",
    "grafana/provisioning/dashboards",
)


def _as_dashboard_json(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(text)
        # Heuristic: a Grafana export typically has at least one of these keys
        if isinstance(data, dict) and ("panels" in data or "dashboard" in data or "templating" in data):
            # Some exports wrap under {"dashboard": {...}}
            return data
    except Exception:
        return None
    return None


def _set_ds(value: Any, name: str) -> Any:
    """Return a datasource field coerced to string name, removing uid/type if object.

    Grafana accepts a plain string datasource name in most places; this avoids unknown uid coupling.
    """
    # Always return the name as a simple string
    return name


def _patch_panel(panel: dict[str, Any], ds_name: str) -> int:
    changes = 0
    # panel.datasource
    if "datasource" in panel:
        if panel.get("datasource") != ds_name:
            panel["datasource"] = _set_ds(panel.get("datasource"), ds_name)
            changes += 1
    # panel.targets[*].datasource
    targets = panel.get("targets")
    if isinstance(targets, list):
        for t in targets:
            if isinstance(t, dict) and "datasource" in t:
                if t.get("datasource") != ds_name:
                    t["datasource"] = _set_ds(t.get("datasource"), ds_name)
                    # remove uid/type if present in newer object schema remnants
                    for k in ("uid", "type"):
                        if k in t:
                            try:
                                del t[k]
                            except Exception:
                                pass
                    changes += 1
    # nested panels (rows)
    nested = panel.get("panels")
    if isinstance(nested, list):
        for child in nested:
            if isinstance(child, dict):
                changes += _patch_panel(child, ds_name)
    return changes


def _patch_templating(dashboard: dict[str, Any], ds_name: str) -> int:
    changes = 0
    templ = dashboard.get("templating") or dashboard.get("dashboard", {}).get("templating")
    if isinstance(templ, dict):
        lst = templ.get("list")
        if isinstance(lst, list):
            for v in lst:
                if isinstance(v, dict) and "datasource" in v:
                    if v.get("datasource") != ds_name:
                        v["datasource"] = _set_ds(v.get("datasource"), ds_name)
                        changes += 1
    return changes


def _patch_dashboard(data: dict[str, Any], ds_name: str) -> int:
    # If wrapped under {"dashboard": {...}}, operate on that level too
    root = data.get("dashboard") if isinstance(data.get("dashboard"), dict) else data
    changes = 0
    # panels at root level
    panels = root.get("panels") if isinstance(root, dict) else None
    if isinstance(panels, list):
        for p in panels:
            if isinstance(p, dict):
                changes += _patch_panel(p, ds_name)
    changes += _patch_templating(data, ds_name)
    return changes


def _iter_dashboard_files(root: Path) -> Iterable[Path]:
    # First, scan common directories
    for rel in COMMON_DASHBOARD_DIRS:
        d = (root / rel).resolve()
        if d.exists() and d.is_dir():
            yield from d.rglob("*.json")
    # Fallback: scan the whole tree but skip known heavy dirs
    skip = {".git", "venv", "env", "__pycache__", "node_modules", "external"}
    for p in root.rglob("*.json"):
        if any(part in skip for part in p.parts):
            continue
        # Avoid re-yielding files under common dirs
        if any(str(p).startswith(str((root / rel).resolve())) for rel in COMMON_DASHBOARD_DIRS):
            continue
        # Skip known Infinity analytics dashboards to avoid overwriting plugin-specific datasources
        name_lower = p.name.lower()
        if (
            "g6_analytics_infinity" in name_lower
            or name_lower.startswith("g6-analytics-infinity")
        ):
            continue
        # Heuristic check before yielding
        try:
            st = p.stat()
            if st.st_size == 0 or st.st_size > 20_000_000:  # skip huge
                continue
        except Exception:
            continue
        yield p


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch Grafana dashboards to a fixed datasource")
    ap.add_argument("root", nargs="?", default=os.getcwd(), help="Root directory to scan")
    ap.add_argument("--ds-name", default=DEFAULT_DS_NAME, help="Datasource name to apply (default: G6 Prometheus)")
    ap.add_argument("--dry-run", action="store_true", help="Print changes but do not write files")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    ds_name = str(args.ds_name)
    dry_run = bool(args.dry_run)

    if not root.exists():
        print(f"error: root does not exist: {root}")
        return 2

    total_files = 0
    patched_files = 0
    total_changes = 0

    for path in _iter_dashboard_files(root):
        data = _as_dashboard_json(path)
        if not data:
            continue
        total_files += 1
        before = json.dumps(data, sort_keys=True, separators=(",", ":"))
        changes = _patch_dashboard(data, ds_name)
        after = json.dumps(data, sort_keys=True, separators=(",", ":"))
        if changes and before != after:
            patched_files += 1
            total_changes += changes
            print(f"patched: {path} (+{changes})")
            if not dry_run:
                bak = path.with_suffix(path.suffix + ".bak")
                try:
                    if not bak.exists():
                        path.replace(bak)
                    else:
                        # If backup exists, proceed without replacing it
                        pass
                except Exception:
                    # If replace fails, fall back to write without backup
                    pass
                try:
                    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                except Exception as e:
                    print(f"error: failed to write {path}: {e}")
        else:
            # No changes needed
            pass

    print(f"summary: dashboards_scanned={total_files} files_patched={patched_files} changes={total_changes}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI tool
    raise SystemExit(main())
