# Test Plan: Override Safety and Auto-Revert

This document outlines the scenarios and acceptance checks for override governance.

Scenarios:
- TTL expiry removes override and exporter returns to k_smooth selection.
- Coverage re-stabilization (both fast/slow windows within tolerance for sustain_period) triggers auto-revert when enabled.
- Audit enrichment: POST includes actor, reason, class; log lines contain these fields.

Test cases (to implement):
1) TTL expiry only
   - Create override with expires_ms in near future; simulate a few cycles; verify applied_k_source moves from override -> smooth, and no override present in /k_overrides.

2) Auto-revert on stabilized coverage
   - Enable auto-revert in exporter/daemon; force coverage back within tolerance; wait sustain_period; verify override cleared.

3) Audit enrichment presence
   - POST override with actor, reason, class; check <INDEX>_ensemble_k_overrides.log line contains these fields and /k_overrides returns them.

## Auto-Revert (Implementation Added in Exporter)

Planned test cases after enabling `--override-auto-revert`:

1. Stable coverage removal:
   - Create calibration sidecar with coverage_fast/coverage_slow values inside tolerance for successive cycles.
   - Run exporter twice with `--override-auto-revert --override-target-tolerance 0.01 --override-sustain-cycles 2` and existing override horizon entry.
   - Verify JSON overrides file no longer lists the horizon after second cycle; audit log contains `AUTO_REMOVE,reason=coverage_stable` line.

2. Dry-run mode:
   - Same setup but include `--dry-run-overrides`; horizon override remains, audit log still records intent `AUTO_REMOVE`.

3. Mixed stability reset:
   - First cycle stable, second cycle out-of-tolerance -> stable_cycles resets; override persists.
   - Third & fourth cycles stable -> removal after fourth cycle.

4. TTL vs stability precedence:
   - Override with expires timestamp earlier than sufficient stability cycles.
   - Ensure TTL removal occurs first and logs `ttl_expired`; stability removal not duplicated.

5. Missing coverage windows:
   - calibration sidecar lacks coverage_fast/slow (disabled adaptive target) -> stability never triggers removal; ensure override persists until TTL.

Helpers to build: fixture to synthesize calibration sidecar JSON between exporter cycles; utility to read audit log lines.

Notes:
- Requires exporter with auto-revert logic and endpoint adjustments; tracked in roadmap Phase 10.
