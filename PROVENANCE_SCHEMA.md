# Delegation Pack C: Config Provenance Schema (Scaffold)

## Goals
- Ensure traceable, verifiable config lineage from authoring to deployment.
- Bind configs to signed manifests with reproducible hashes and dependency references.

## Manifest Structure (JSON)
- `version`: string (schema version)
- `config_index`: string (e.g., NIFTY)
- `config_hash`: sha256 of canonical JSON (sorted keys, compact separators)
- `signing`: { `algorithm`: "HMAC-SHA256", `key_id`: string }
- `timestamp_utc`: ISO 8601
- `actor`: { `name`: string, `email`: string }
- `dependencies`: [ { `name`: string, `version`: string, `hash`: string } ]
- `artifacts`: [ { `path`: string, `hash`: string } ]
- `previous_hash`: optional sha256 link to prior manifest
- `notes`: optional string

## Canonicalization Rules
- JSON dump with `sort_keys=True`, separators `(, :)`, UTF-8
- Hash computed over canonical config JSON; artifact hashes are sha256(file bytes)

## Verification Steps
1. Compute `config_hash` from provided config JSON (canonical).
2. Recompute HMAC signature using `CONFIG_SIGNING_KEY`; compare digest.
3. Validate artifact and dependency hashes against provided files.
4. Check `previous_hash` matches last recorded manifest (chain integrity).

## Integration Points
- Extend `/api/ml/ensemble/config_integrity` to optionally return manifest digest & chain link.
- CLI stubs: `g6-provenance` to generate manifests; `g6-release-automation` to verify and bundle.

## Acceptance Criteria
- All configs shipped with a manifest.
- Verification fails on any hash mismatch or missing artifact.
- CI job validates manifests on PRs.