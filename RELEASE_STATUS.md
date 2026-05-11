# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13b1`
- Latest released version: `1.0.13b1`
- Latest published release: `1.0.13b1`
- Latest published tag: `v1.0.13b1`
- Current branch for release preparation: `main`
- Release candidate under canary record: active `docs/canary-evidence/c17c749/` bundle for `v1.0.13b1`
- Release publish action: no release flow is in progress.

## Current Posture

- Published package baseline is now `v1.0.13b1`.
- The `1.0.13b1` beta release extends `1.0.13a12` with stricter real-world returns validation for malformed and incomplete `details` handling.
- The retained Phase 16 canary bundle for `v1.0.13a11` remains at `docs/canary-evidence/1af2d8d/` as historical evidence and is explicitly superseded by the `v1.0.13a12` publication path.
- A fresh candidate-specific canary bundle is now open for `c17c749` / `v1.0.13b1`; the canary has reached the 10-workflows checkpoint with `10/11` accepted workflows, one `code_validation` incident, and zero rollbacks.
- Broader rollout and go-live claims remain blocked while that incident is under review.

## Repository Release Gate

- The deterministic repository release gate is green on `c17c749`.
- The GitHub prerelease for `v1.0.13b1` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`.
- The current canary evidence for `c17c749` records a clean `3/3` first-admitted batch, a `10-workflows` checkpoint at `9/10` accepted with one `code_validation` incident, and a clean targeted rerun that brought the cumulative state to `10/11` accepted.
- No release workflow is currently in progress.

## Next Release-Facing Action

1. Review the recorded `code_validation` incident on `c17c749` before any broader canary expansion.
2. Keep broader rollout and go-live claims blocked until the beta canary satisfies the repository policy.
3. Decide on the next development-line move only after the beta canary path is clearer.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)