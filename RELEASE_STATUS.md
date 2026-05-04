# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a11`
- Latest released version: `1.0.13a11`
- Latest published release: `1.0.13a11`
- Latest published tag: `v1.0.13a11`
- Current branch for release preparation: `main`
- Release publish action: tag `v1.0.13a11` pushed; release workflow in progress.

## Current Posture

- Published package baseline is `v1.0.13a11`.
- The `1.0.13a11` release extends `1.0.13a10` with a comprehensive partial-branch coverage campaign, raising branch coverage from 99.19% to 99.89% (2568 tests).
- The current line satisfies the local Beta 1 minimum as an internal checkpoint; that does not automatically open canary or go-live posture.

## Repository Release Gate

- The deterministic repository release gate is green on `ab26b1b`.
- `ruff` and the full pytest suite (2568 tests) are clean.
- Coverage: 99.89% (23 dead-code branch misses accepted, 2 dead-code statement misses accepted).
- Release workflow triggered by tag `v1.0.13a11`.

## Next Release-Facing Action

1. Verify release workflow completes successfully on GitHub Actions.
2. Confirm wheel, sdist, manifest, and promotion summary are published.
3. Decide whether to open Phase 16 canary admission on the current head.
4. Keep canary and go-live decisions separately gated.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)