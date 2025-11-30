"""g6-provenance: Generate and verify config provenance manifests.

Usage (PowerShell):
  python scripts/g6_provenance.py generate --index NIFTY --config configs/ml/nifty_ensemble_config.json --key-id default --out provenance_NIFTY.json
  python scripts/g6_provenance.py verify --manifest provenance_NIFTY.json --config configs/ml/nifty_ensemble_config.json
"""
from __future__ import annotations
import argparse, json, hashlib, hmac, os
from datetime import datetime, timezone

def canonical_json(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")

def sha256_bytes(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()

def get_key_bytes() -> bytes | None:
    key = os.environ.get("CONFIG_SIGNING_KEY", "")
    if not key:
        return None
    try:
        if all(c in "0123456789abcdefABCDEF" for c in key) and len(key) % 2 == 0:
            return bytes.fromhex(key)
    except Exception:
        pass
    return key.encode("utf-8")

def sign_hmac(payload: bytes) -> str:
    key = get_key_bytes()
    if key is None:
        return sha256_bytes(payload)
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

def cmd_generate(args: argparse.Namespace) -> int:
    cfg_path = args.config
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg_hash = sha256_bytes(canonical_json(cfg))
    manifest = {
        "version": "1.0",
        "config_index": args.index.upper(),
        "config_hash": cfg_hash,
        "signing": {"algorithm": "HMAC-SHA256", "key_id": args.key_id},
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "actor": {"name": os.environ.get("G6_ACTOR_NAME", "unknown"), "email": os.environ.get("G6_ACTOR_EMAIL", "unknown@example")},
        "dependencies": [],
        "artifacts": [{"path": cfg_path, "hash": cfg_hash}],
        "previous_hash": args.previous_hash,
        "notes": args.notes,
    }
    sig = sign_hmac(canonical_json(cfg))
    manifest["signature"] = sig
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest: {args.out}")
    return 0

def cmd_verify(args: argparse.Namespace) -> int:
    with open(args.manifest, "r", encoding="utf-8") as f:
        m = json.load(f)
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    expected_hash = sha256_bytes(canonical_json(cfg))
    if m.get("config_hash") != expected_hash:
        print("ERROR: config_hash mismatch")
        return 2
    expected_sig = sign_hmac(canonical_json(cfg))
    if m.get("signature") != expected_sig:
        print("ERROR: signature mismatch")
        return 3
    print("Manifest verification OK")
    return 0

def main() -> int:
    p = argparse.ArgumentParser("g6-provenance")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--index", required=True)
    g.add_argument("--config", required=True)
    g.add_argument("--key-id", default="default")
    g.add_argument("--out", required=True)
    g.add_argument("--previous-hash", default=None)
    g.add_argument("--notes", default=None)
    g.set_defaults(func=cmd_generate)
    v = sub.add_parser("verify")
    v.add_argument("--manifest", required=True)
    v.add_argument("--config", required=True)
    v.set_defaults(func=cmd_verify)
    args = p.parse_args()
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())