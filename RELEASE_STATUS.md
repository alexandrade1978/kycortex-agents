# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13b1`
- Latest released version: `1.0.13a12`
- Latest published release: `1.0.13a12`
- Latest published tag: `v1.0.13a12`
- Current branch for release preparation: `main`
- Release candidate under canary record: preparing `v1.0.13b1`
- Release publish action: preparing `v1.0.13b1` for tag and workflow publication.

## Current Posture

- Published package baseline remains `v1.0.13a12` until `v1.0.13b1` is published.
- The `1.0.13b1` beta candidate extends `1.0.13a12` with stricter real-world returns validation for malformed and incomplete `details` handling.
- The retained Phase 16 canary bundle for `v1.0.13a11` remains at `docs/canary-evidence/1af2d8d/` as historical evidence and is explicitly superseded by the `v1.0.13a12` publication path.
- No active canary record is currently open for the upcoming `v1.0.13b1` candidate; any broader rollout claim will require a fresh candidate-specific canary bundle after publication.

## Repository Release Gate

- The latest published deterministic repository release gate remains green on `v1.0.13a12`.
- The `v1.0.13a12` GitHub release published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`.
- The current `v1.0.13b1` candidate still needs the local release gate rerun before tagging.
- No release workflow is currently in progress.

## Next Release-Facing Action

1. Run the full local release gate for `v1.0.13b1`.
2. Publish the release-preparation commit and push tag `v1.0.13b1`.
3. Open the candidate-specific canary path only after the beta publication closes cleanly.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)