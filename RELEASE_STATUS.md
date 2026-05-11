# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a13.dev0`
- Latest released version: `1.0.13a12`
- Latest published release: `1.0.13a12`
- Latest published tag: `v1.0.13a12`
- Current branch for release preparation: `main`
- Release candidate under canary record: none currently open
- Release publish action: no release flow is in progress.

## Current Posture

- Published package baseline is now `v1.0.13a12`.
- The `1.0.13a12` release extends `1.0.13a11` with hardened release-user-smoke qualification through scenario rotation and strict typing for the new scenario profiles.
- The retained Phase 16 canary bundle for `v1.0.13a11` remains at `docs/canary-evidence/1af2d8d/` as historical evidence and is explicitly superseded by the `v1.0.13a12` publication path.
- No active canary record is currently open for `v1.0.13a12`; any broader rollout claim will require a fresh candidate-specific canary bundle.

## Repository Release Gate

- The deterministic repository release gate is green on `89d6e13`.
- The GitHub release for `v1.0.13a12` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`.
- The retained empirical floor includes the clean `v1.0.13a11` canary evidence and the release-user-smoke scenario-rotation improvements now versioned in `v1.0.13a12`.
- No release workflow is currently in progress.

## Next Release-Facing Action

1. Decide whether to open a fresh canary path for `v1.0.13a12` or keep the release at package-publication scope only.
2. Continue milestone engineering on `1.0.13a13.dev0`.
3. Keep canary and go-live decisions separately gated from package publication.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)