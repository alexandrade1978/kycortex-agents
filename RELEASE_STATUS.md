# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13b2`
- Latest released version: `1.0.13b1`
- Latest published release: `1.0.13b1`
- Latest published tag: `v1.0.13b1`
- Current branch for release preparation: `main`
- Release candidate under canary record: held `docs/canary-evidence/c17c749/` bundle for `v1.0.13b1`
- Release publish action: replacement beta candidate `1.0.13b2` passed the repository release gate and is ready for tag/publish.

## Current Posture

- Published package baseline is now `v1.0.13b1`.
- The `1.0.13b1` beta release extends `1.0.13a12` with stricter real-world returns validation for malformed and incomplete `details` handling.
- The retained Phase 16 canary bundle for `v1.0.13a11` remains at `docs/canary-evidence/1af2d8d/` as historical evidence and is explicitly superseded by the `v1.0.13a12` publication path.
- The validated `1.0.13b2.dev0` fix line is now frozen into replacement beta candidate `1.0.13b2` while published `v1.0.13b1` remains the latest released beta baseline.
- The candidate-specific beta canary bundle for `c17c749` / `v1.0.13b1` is now on policy hold after the early window reached only `10/11` accepted workflows, retained one `code_validation` incident, and stayed below the `>=95.0%` accepted-workflow target.
- Same-candidate canary expansion remains frozen; the active replacement path is publication and fresh canary admission on `1.0.13b2`.
- Broader rollout and go-live claims remain blocked.

## Repository Release Gate

- The deterministic repository release gate is green on replacement beta candidate `1.0.13b2`.
- Both `scripts/release_check.py` and `make release-check` passed on the frozen `1.0.13b2` candidate.
- The GitHub prerelease for `v1.0.13b1` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`.
- The current canary evidence for `c17c749` records a clean `3/3` first-admitted batch, a `10-workflows` checkpoint at `9/10` accepted with one `code_validation` incident, and a clean targeted rerun that brought the cumulative state to `10/11` accepted; the retained rate remains below policy and keeps the bundle on hold.
- Replacement beta candidate `1.0.13b2` now carries the validated follow-on fix for the held beta path.
- No release workflow is currently in progress.

## Next Release-Facing Action

1. Publish the validated freeze slice for replacement beta candidate `1.0.13b2`.
2. Tag and push `v1.0.13b2`, then verify the tagged release workflow and prerelease assets.
3. Keep broader rollout and go-live claims blocked until the replacement candidate re-enters a policy-compliant beta canary.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)