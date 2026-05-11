# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13b2`
- Latest released version: `1.0.13b2`
- Latest published release: `1.0.13b2`
- Latest published tag: `v1.0.13b2`
- Current branch for release preparation: `main`
- Release candidate under canary record: active `docs/canary-evidence/1e68a8b/` bundle for `v1.0.13b2`
- Release publish action: no release flow is in progress.

## Current Posture

- Published package baseline is now `v1.0.13b2`.
- The `1.0.13b2` beta release extends `1.0.13b1` with a safer default completion budget for `release-user-smoke` and explicit `--max-tokens` override support for future canary tuning.
- The retained Phase 16 canary bundle for `v1.0.13a11` remains at `docs/canary-evidence/1af2d8d/` as historical evidence and is explicitly superseded by the `v1.0.13a12` publication path.
- The candidate-specific beta canary bundle for `c17c749` / `v1.0.13b1` is now on policy hold after the early window reached only `10/11` accepted workflows, retained one `code_validation` incident, and stayed below the `>=95.0%` accepted-workflow target.
- The replacement beta canary is active at `docs/canary-evidence/1e68a8b/`; smoke01 through smoke18 closed `50/50` accepted with zero incidents and zero rollbacks, and the early window has now crossed the `50-workflows` checkpoint cleanly.
- Same-candidate canary expansion remains frozen on `c17c749`; the active path is fresh canary admission on `1.0.13b2`.
- Broader rollout and go-live claims remain blocked.

## Repository Release Gate

- The deterministic repository release gate stayed green on published candidate `1.0.13b2`.
- Both `scripts/release_check.py` and `make release-check` passed on the frozen `1.0.13b2` candidate before tagging.
- The GitHub prerelease for `v1.0.13b2` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`.
- Remote verification completed successfully for published commit `1e68a8b`: CI `25665805838` and Release `25665819510` both closed green.
- The current canary evidence for `c17c749` remains retained historical hold evidence for the superseded `v1.0.13b1` candidate.
- The replacement candidate `1e68a8b` / `v1.0.13b2` reached the 50-workflows checkpoint at `2026-05-11T12:06:20Z` with cumulative `50/50` accepted workflows and no incident.
- No release workflow is currently in progress.

## Next Release-Facing Action

1. Continue the replacement beta canary through the `100-workflows` checkpoint for candidate `1e68a8b` / `v1.0.13b2`.
2. Maintain repository-owned checkpoint packets and daily review until the `7`-day/`100`-workflow minimum window closes.
3. Keep broader rollout and go-live claims blocked until the replacement candidate closes a policy-compliant beta canary.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)