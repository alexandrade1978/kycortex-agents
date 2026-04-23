# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a10.dev0`
- Latest published release: `1.0.13a6`
- Latest published tag: `v1.0.13a6`
- Current branch for release preparation: `main`

## Current Posture

- The current development head remains in refactor-engineering mode.
- No active release candidate, canary claim, or production-readiness claim is attached to the current head.
- Historical canary operations and evidence are retained separately and are not summarized here.

## Repository Release Gate

- Deterministic repository release validation is currently green on the development head.
- The latest validated gate includes `ruff`, `mypy`, focused public and package regressions, package validation, release metadata validation, the repository coverage gate, and the full pytest suite.
- A green deterministic gate does not by itself create a new release or production claim.

## Next Release-Facing Action

1. Finish the documentation and governance reset for the current branch.
2. Decide whether the current head should enter a new release-candidate review.
3. If that review is opened, follow [RELEASE.md](RELEASE.md) for package publication and [docs/go-live-policy.md](docs/go-live-policy.md) for any production-readiness claim.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)