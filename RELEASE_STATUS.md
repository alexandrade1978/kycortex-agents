# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a12`
- Latest released version: `1.0.13a11`
- Latest published release: `1.0.13a11`
- Latest published tag: `v1.0.13a11`
- Current branch for release preparation: `main`
- Release candidate under canary record: historical `v1.0.13a11` bundle retained at `docs/canary-evidence/1af2d8d/`
- Release publish action: preparing `v1.0.13a12` for tag and workflow publication.

## Current Posture

- Published package baseline is still `v1.0.13a11` until the `v1.0.13a12` tag is published.
- The `1.0.13a12` release candidate extends `1.0.13a11` with hardened release-user-smoke qualification through scenario rotation and strict typing for the new scenario profiles.
- The retained Phase 16 canary bundle for `v1.0.13a11` remains at `docs/canary-evidence/1af2d8d/` as historical evidence and is not the promotion target for this release slice.
- The deterministic local release gate for `1.0.13a12` is now green on the current `main` head; tag publication is the next release step.
- A fresh canary decision for `v1.0.13a12` will require its own candidate-specific evidence after publication.

## Repository Release Gate

- The previous deterministic repository release gate is green on `1af2d8d` (CI run `25299510656`, Release `25299517420`).
- The current `1.0.13a12` release candidate has cleared the full local release gate on `main` (`release_metadata_check`, `make release-metadata-check`, `release_check`, `make release-check`).
- The retained empirical floor includes the clean `v1.0.13a11` canary evidence and the release-user-smoke scenario-rotation improvements now versioned in the `1.0.13a12` candidate line.
- No release workflow is currently in progress.

## Next Release-Facing Action

1. Publish the release-preparation commit for `1.0.13a12`.
2. Push tag `v1.0.13a12` and verify the GitHub release workflow.
3. After publication, open a fresh candidate-specific canary path if release expansion beyond package publication is still desired.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)