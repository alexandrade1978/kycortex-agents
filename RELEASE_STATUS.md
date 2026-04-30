# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a10.dev0`
- Latest released version: `1.0.13a6`
- Latest published release: `1.0.13a6`
- Latest published tag: `v1.0.13a6`
- Current branch for release preparation: `main`
- Current main-branch head: `896bcf1`
- Release publish action: no release flow is in progress.

## Current Posture

- Published package baseline remains `v1.0.13a6`.
- Current main-branch head `896bcf1` is green on the repository CI, but it is not yet a tagged or released package candidate.
- The current line still satisfies the local Beta 1 minimum as an internal checkpoint; that does not automatically open release, canary, or go-live posture.
- Release-candidate review is not open.

## Repository Release Gate

- The deterministic repository release gate is green on `896bcf1`.
- The latest post-push `mypy` and coverage remediation is included in that green branch state.
- No release workflow is currently in progress.

## Next Release-Facing Action

1. Decide whether to open release-candidate review for `896bcf1` or keep it as a branch-only checkpoint.
2. If publication is approved, run `RELEASE.md` end-to-end on the same head.
3. Keep canary and go-live decisions separately gated beyond this branch state.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)