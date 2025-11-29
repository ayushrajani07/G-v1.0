"""Config signing & integrity verification (Phase 13).

Uses HMAC-SHA256 with secret env var CONFIG_SIGNING_KEY (hex or raw string).
Provides API:
    sign_config(index, cfg) -> signature hex
    verify_config(index, cfg, signature) -> bool
Maintains last signature per index for integrity endpoint exposure.
Falls back to deterministic hash if key missing.
"""
from __future__ import annotations
import os, hmac, hashlib, json, threading
from typing import Dict, Any

_LOCK = threading.Lock()
_LATEST_SIG: Dict[str, str] = {}

def _get_key() -> bytes | None:
    key = os.environ.get('CONFIG_SIGNING_KEY','')
    if not key:
        return None
    # Allow hex-encoded key
    try:
        if all(c in '0123456789abcdefABCDEF' for c in key) and len(key) % 2 == 0:
            return bytes.fromhex(key)
    except Exception:
        pass
    return key.encode('utf-8')

def _canonical(cfg: Dict[str, Any]) -> bytes:
    return json.dumps(cfg, sort_keys=True, separators=(',',':')).encode('utf-8')

def sign_config(index: str, cfg: Dict[str, Any]) -> str:
    payload = _canonical(cfg)
    key = _get_key()
    if key is None:
        # Fallback unsigned hash
        sig = hashlib.sha256(payload).hexdigest()
    else:
        sig = hmac.new(key, payload, hashlib.sha256).hexdigest()
    idx = index.upper()
    with _LOCK:
        _LATEST_SIG[idx] = sig
    return sig

def verify_config(index: str, cfg: Dict[str, Any], signature: str) -> bool:
    expected = sign_config(index, cfg)
    # sign_config stores latest; we recompute; constant-time compare
    return hmac.compare_digest(expected, signature)

def latest_signature(index: str) -> str | None:
    with _LOCK:
        return _LATEST_SIG.get(index.upper())

__all__ = ['sign_config','verify_config','latest_signature']