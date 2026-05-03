# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a10`
- Latest released version: `1.0.13a10`
- Latest published release: `1.0.13a10`
- Latest published tag: `v1.0.13a10`
- Current branch for release preparation: `main`
- Current main-branch head: `8998d03` (pre-tag; will update after release commit)
- Release publish action: release `v1.0.13a10` in progress.

## Current Posture

- Published package baseline is `v1.0.13a10`.
- This release contains the orchestrator refactor (owner-module migration) and a comprehensive test coverage campaign reaching 99.19% statement coverage.
- The current line satisfies the local Beta 1 minimum as an internal checkpoint; that does not automatically open canary or go-live posture.
- Release-candidate review is not open for further versions yet.

## Repository Release Gate

- The deterministic repository release gate is green on `8998d03`.
- `ruff`, `mypy`, and the full pytest suite (2474 tests) are clean.
- Coverage: 99.19% (2 dead-code statement misses accepted).
- No release workflow is currently in progress beyond `v1.0.13a10` tagging.

## Next Release-Facing Action

1. Push `v1.0.13a10` tag and confirm CI release workflow.
2. Decide whether to open Phase 16 canary admission on the current head.
3. Keep canary and go-live decisions separately gated beyond this release state.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)