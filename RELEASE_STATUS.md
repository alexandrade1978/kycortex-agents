# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13b1`
- Latest released version: `1.0.13b1`
- Latest published release: `1.0.13b1`
- Latest published tag: `v1.0.13b1`
- Current branch for release preparation: `main`
- Release candidate under canary record: held `docs/canary-evidence/c17c749/` bundle for `v1.0.13b1`
- Release publish action: no release flow is in progress.

## Current Posture

- Published package baseline is now `v1.0.13b1`.
- The `1.0.13b1` beta release extends `1.0.13a12` with stricter real-world returns validation for malformed and incomplete `details` handling.
- The retained Phase 16 canary bundle for `v1.0.13a11` remains at `docs/canary-evidence/1af2d8d/` as historical evidence and is explicitly superseded by the `v1.0.13a12` publication path.
- The candidate-specific beta canary bundle for `c17c749` / `v1.0.13b1` is now on policy hold after the early window reached only `10/11` accepted workflows, retained one `code_validation` incident, and stayed below the `>=95.0%` accepted-workflow target.
- Same-candidate canary expansion is frozen until the retained incident is root-caused and an explicit retry-or-replace decision is recorded.
- Broader rollout and go-live claims remain blocked.

## Repository Release Gate

- The deterministic repository release gate is green on `c17c749`.
- The GitHub prerelease for `v1.0.13b1` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`.
- The current canary evidence for `c17c749` records a clean `3/3` first-admitted batch, a `10-workflows` checkpoint at `9/10` accepted with one `code_validation` incident, and a clean targeted rerun that brought the cumulative state to `10/11` accepted; the retained rate remains below policy and keeps the bundle on hold.
- No release workflow is currently in progress.

## Next Release-Facing Action

1. Root-cause the retained `code_validation` incident on `c17c749` and decide whether the candidate is explicitly retriable.
2. If the incident cannot be explained cleanly, prepare a replacement candidate instead of resuming the held bundle.
3. Keep broader rollout and go-live claims blocked until a policy-compliant beta canary resumes.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)