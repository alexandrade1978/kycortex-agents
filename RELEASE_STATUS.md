# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a10.dev0`
- Latest released version: `1.0.13a6`
- Latest published release: `1.0.13a6`
- Latest published tag: `v1.0.13a6`
- Current branch for release preparation: `main`
- Current branch head is actively maintained on `main`; use repository history for the exact commit lineage.

## Coverage Status

- **Test Count**: 1952 tests (up from 1913 baseline)
- **Coverage**: 96.66% (251 missing statements of 13,813 total)
- **Coverage Threshold**: 90% minimum (current: 96.66%, exceeds requirement)
- **Recent Improvements**: 
  - Fixed case-sensitivity bug in `_summary_has_active_issue()`
  - Added 39 direct unit tests for qa_tester and architect modules
  - Covered 6 additional lines in coverage improvements

## Current Posture

- The current development head is stable with comprehensive test coverage and passing CI.
- The current development head includes a feature-flagged adaptive prompt-policy core for model-aware compaction behavior (`compact`, `balanced`, `rich`) while preserving legacy defaults.
- The provider-matrix empirical workflow helpers now support configurable timeout and prompt-budget envelopes for code/test task constraints while preserving previous defaults.
- Runtime validation now applies adaptive-policy-aware secondary line-budget tolerance (`compact=0%`, `balanced=5%`, `rich=15%`) while keeping contract mismatch, syntax/import, CLI-entrypoint, and truncation failures as strict blockers.
- Documentation governance has been applied; all public/internal boundaries are respected.
- Release-candidate review is now open for the current `main` head.
- No canary claim or production-readiness claim is attached to the current head.
- Repository is in excellent operational state for package-level release review.
- Historical canary operations and evidence are retained separately and are not summarized here.

## Repository Release Gate

- Deterministic repository release validation is currently green on the development head.
- The latest validated gate includes `ruff`, `mypy`, focused public and package regressions, package validation, release metadata validation, the repository coverage gate, and the full pytest suite.
- A green deterministic gate does not by itself create a new release or production claim.

## Next Release-Facing Action

1. Complete release-candidate review sign-off for the current `main` head.
2. If approved, follow [RELEASE.md](RELEASE.md) to create and push the next version tag.
3. Keep go-live claims gated by [docs/go-live-policy.md](docs/go-live-policy.md); release review does not imply production-readiness.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)