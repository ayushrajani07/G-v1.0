"""Config versioning + diff export (Phase 12).

Maintains per-index JSONL history of ensemble configs with hash and timestamp.
Provides utility to compute diff (added/removed/changed keys at shallow level).
"""
from __future__ import annotations
import json, hashlib, time
from pathlib import Path
from typing import Dict, Any

_HISTORY_DIR = Path(__file__).resolve().parent.parent.parent / 'data' / 'config_versions'
_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

def _hash_config(cfg: Dict[str, Any]) -> str:
    payload = json.dumps(cfg, sort_keys=True, separators=(',',':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()

def record_config(index: str, cfg: Dict[str, Any]) -> str:
    index_u = index.upper()
    h = _hash_config(cfg)
    path = _HISTORY_DIR / f"{index_u}.jsonl"
    entry = {'timestamp': time.time(), 'hash': h, 'config': cfg}
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry)+'\n')
    return h

def load_history(index: str) -> list[Dict[str, Any]]:
    path = _HISTORY_DIR / f"{index.upper()}.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out

def shallow_diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    added = {k: new[k] for k in new.keys() - old.keys()}
    removed = {k: old[k] for k in old.keys() - new.keys()}
    changed = {k: {'old': old[k], 'new': new[k]} for k in old.keys() & new.keys() if old[k] != new[k]}
    return {'added': added, 'removed': removed, 'changed': changed}

def latest_diff(index: str) -> Dict[str, Any]:
    hist = load_history(index)
    if len(hist) < 2:
        return {'error': 'insufficient_history', 'count': len(hist)}
    old = hist[-2]['config']
    new = hist[-1]['config']
    return {'index': index.upper(), 'latest_hash': hist[-1]['hash'], 'prev_hash': hist[-2]['hash'], 'diff': shallow_diff(old, new), 'count': len(hist)}
