# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a12.dev0`
- Latest released version: `1.0.13a11`
- Latest published release: `1.0.13a11`
- Latest published tag: `v1.0.13a11`
- Current branch for release preparation: `main`
- Current main-branch head: `1af2d8d` (release commit; tag `v1.0.13a11` points here)
- Release publish action: no release flow is in progress.

## Current Posture

- Published package baseline is `v1.0.13a11`.
- The `1.0.13a11` release extends `1.0.13a10` with a comprehensive partial-branch coverage campaign, reaching 99.89% branch coverage (2568 tests).
- The current line satisfies the local Beta 1 minimum as an internal checkpoint; that does not automatically open canary or go-live posture.
- Release-candidate review is not open for further versions yet.

## Repository Release Gate

- The deterministic repository release gate is green on `1af2d8d` (CI run `25299510656`, Release `25299517420`).
- `ruff`, `mypy`, and the full pytest suite (2568 tests) are clean.
- Coverage: 99.89% (23 dead-code branch misses accepted, 2 dead-code statement misses accepted).
- No release workflow is currently in progress.

## Next Release-Facing Action

1. Decide whether to open Phase 16 canary admission on the current head.
2. Prepare engineering for next milestone.
3. Keep canary and go-live decisions separately gated.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)