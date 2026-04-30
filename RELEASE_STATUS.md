# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a10.dev0`
- Latest released version: `1.0.13a6`
- Latest published release: `1.0.13a6`
- Latest published tag: `v1.0.13a6`
- Current branch for release preparation: `main`
- Release publish action: none pending in this slice; the branch gate is green again on `main`.

## Current Posture

- Published `main` is healthy again: the latest CI run `25143941647` completed green on head `2e840be` after superseding the earlier `Coverage Gate` and `Focused Regressions` failures.
- Release-candidate review remains closed.
- The latest canonical full-scope root at `output/real_world_complex_matrix_2026_04_30_head501a3a1_full_scope_post_returns_anthropic_recovery_rerun` is terminal but non-clean: `13` completed cells, `2` degraded cells, `0` active cells, `0` unstarted cells.
- The remaining degraded checkpoints on that root are `kyc_compliance_intake/anthropic` and `access_review_audit/ollama`.
- No canary claim or production-readiness claim is attached to the current head.

## Repository Release Gate

- GitHub Actions is green again on the published head `2e840be`, including `Lint and Typecheck`, both `Focused Regressions` jobs, `Package Validation`, `Coverage Gate`, and both `Full Test Suite` jobs.
- The local fix sequence re-cleared the exact former coverage blocker with:
  - `./.venv/bin/python -m pytest --cov=kycortex_agents --cov-report=term-missing --cov-report=xml -q`
  - result: `1994 passed`, total coverage `95.74%`
- The release-status follow-up slice also re-cleared the exact former focused-regressions command after restoring the expected `RELEASE_STATUS.md` headings and published-release line:
  - `./.venv/bin/python -m pytest tests/test_public_api.py tests/test_public_smoke.py tests/test_package_metadata.py -q`
  - result: `81 passed`
- The same validated slice also kept `ruff`, `mypy`, and `scripts/package_check.py` green before publication.

## Next Release-Facing Action

1. Keep release-candidate review closed until a fresh post-fix canonical rerun proves a clean `15/15` result.
2. Use the now-green branch gate as the deterministic baseline for that rerun.
3. Publish a new package release only after the empirical gate is also clean.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)