# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a10.dev0`
- Latest released version: `1.0.13a6`
- Latest published release: `1.0.13a6`
- Latest published tag: `v1.0.13a6`
- Current branch for release preparation: `main`
- Release publish action: none pending in this slice; the immediate task is CI recovery on `main`.

## Current Posture

- Published `main` is still not healthy because run `25143365604` failed at `Coverage Gate`, and follow-up run `25143829892` then failed at `Focused Regressions` on the release-status snapshot contract.
- Release-candidate review remains closed.
- The latest canonical full-scope root at `output/real_world_complex_matrix_2026_04_30_head501a3a1_full_scope_post_returns_anthropic_recovery_rerun` is terminal but non-clean: `13` completed cells, `2` degraded cells, `0` active cells, `0` unstarted cells.
- The remaining degraded checkpoints on that root are `kyc_compliance_intake/anthropic` and `access_review_audit/ollama`.
- No canary claim or production-readiness claim is attached to the current head.

## Repository Release Gate

- Published `main` is currently red because GitHub Actions run `25143365604` failed at `Coverage Gate` and skipped the dependent full-suite job.
- The local unpublished fix slice has re-cleared the exact failing gate with:
  - `./.venv/bin/python -m pytest --cov=kycortex_agents --cov-report=term-missing --cov-report=xml -q`
  - result: `1994 passed`, total coverage `95.74%`
- The immediate follow-up slice also re-cleared the exact failed focused-regressions command after restoring the expected `RELEASE_STATUS.md` headings and published-release line:
  - `./.venv/bin/python -m pytest tests/test_public_api.py tests/test_public_smoke.py tests/test_package_metadata.py -q`
  - result: `81 passed`
- The same local slice also keeps the earlier deterministic checks green: `ruff`, `mypy`, and `scripts/package_check.py`.

## Next Release-Facing Action

1. Commit and push the validated coverage-gate fix slice.
2. Commit and push the release-status follow-up fix, then follow the new GitHub Actions rerun until `Focused Regressions`, `Coverage Gate`, and the full suite are green.
3. Keep release-candidate review closed until a fresh post-fix canonical rerun proves a clean `15/15` result.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)