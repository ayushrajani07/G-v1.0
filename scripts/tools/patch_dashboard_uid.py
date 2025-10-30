#!/usr/bin/env python3
"""
Patch a Grafana dashboard JSON to switch Infinity datasource UID INFINITY -> G6_INFINITY.

Usage:
  python scripts/tools/patch_dashboard_uid.py <input.json> <output.json>

Notes:
- Only updates datasource objects of type yesoreyeram-infinity-datasource.
- Recurses panels and targets; preserves everything else verbatim.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


INFINITY_TYPE = "yesoreyeram-infinity-datasource"
SRC_UID = "INFINITY"
DST_UID = "G6_INFINITY"


def _patch_ds_obj(obj: Any) -> bool:
    """If obj looks like a Grafana datasource object with uid=INFINITY and Infinity type, switch uid.

    Returns True if a change was made.
    """
    if isinstance(obj, dict):
        t = obj.get("type")
        uid = obj.get("uid")
        if t == INFINITY_TYPE and uid == SRC_UID:
            obj["uid"] = DST_UID
            return True
    return False


def _walk_patch(node: Any) -> int:
    changed = 0
    if isinstance(node, dict):
        # Direct datasource on panel
        if "datasource" in node:
            if _patch_ds_obj(node.get("datasource")):
                changed += 1
        # Targets[*].datasource
        ts = node.get("targets")
        if isinstance(ts, list):
            for t in ts:
                if isinstance(t, dict) and "datasource" in t:
                    if _patch_ds_obj(t.get("datasource")):
                        changed += 1
        # Templating list entries may also contain datasource objects
        templ = node.get("templating")
        if isinstance(templ, dict):
            lst = templ.get("list")
            if isinstance(lst, list):
                for v in lst:
                    if isinstance(v, dict) and "datasource" in v:
                        if _patch_ds_obj(v.get("datasource")):
                            changed += 1
        # Recurse into children
        for k, v in list(node.items()):
            changed += _walk_patch(v)
    elif isinstance(node, list):
        for item in node:
            changed += _walk_patch(item)
    return changed


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: patch_dashboard_uid.py <input.json> <output.json>")
        return 2
    inp = Path(argv[1])
    out = Path(argv[2])
    if not inp.exists():
        print(f"error: input not found: {inp}")
        return 2
    try:
        data = json.loads(inp.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        print(f"error: failed to parse JSON: {e}")
        return 2
    changes = _walk_patch(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"patched: {changes} changes -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
