# Release Status

This file tracks the current repository-owned release-readiness state for KYCortex while the project closes out the 1.0 release candidate.

## Current State

- Package version in `pyproject.toml`: `0.1.0`
- Release target under final Phase 13 review: `1.0.0`
- Branch expected for release preparation: `main`

## Repository Release Gates

- Local release validation is available through `python scripts/release_check.py` and `make release-check`.
- Built package artifacts are validated through `scripts/package_check.py`.
- Repository coverage is enforced through the `pytest-cov` gate configured in `pyproject.toml`.
- Tagged release automation is defined in `.github/workflows/release.yml`.
- Changelog and migration guidance are maintained in `CHANGELOG.md` and `MIGRATION.md`.

## Latest Validated Release-Readiness Pass

- `ruff`: passing
- `mypy`: passing
- focused public and metadata regressions: passing
- package validation: passing
- coverage gate: passing
- full pytest suite: passing

## Remaining Manual Decision

The remaining release action is a human decision to update the package version for the intended release and push the final version tag after reviewing the current release guide and checklist.

Use the following repository-owned references before tagging:

- `RELEASE.md`
- `.local-docs/release-checklist.md`
- `CHANGELOG.md`
- `MIGRATION.md`

## Next Release Action

When the final release decision is made:

1. update the package version for the intended release
2. rerun `python scripts/release_check.py`
3. create and push the matching `v<version>` tag
4. verify the tagged GitHub release workflow and attached artifacts