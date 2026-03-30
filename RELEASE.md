# Release Guide

This document describes the repository-owned release procedure for KYCortex 1.0.0 and later maintenance releases, including alpha-style pre-releases.

## Preconditions

- Work from a clean checkout of `main`.
- Confirm the version in `pyproject.toml` is the version you intend to tag.
- For alpha or other pre-releases, use a PEP 440 package version such as `1.0.13a1` and push the matching Git tag `v1.0.13a1`.
- Confirm `CHANGELOG.md` and `MIGRATION.md` reflect the release you intend to publish.
- Confirm `README.md`, `COMMERCIAL_LICENSE.md`, and related contributor guidance reflect any licensing-policy changes included in the release.
- Confirm the current release checklist in `.local-docs/release-checklist.md` has been reviewed.

## Local Validation

Run the repository-owned release validation pass before creating a tag:

```bash
python scripts/release_metadata_check.py
make release-metadata-check
python scripts/release_check.py
make release-check
```

This executes the same local release-readiness sequence used for tagged releases:

- `ruff`
- `mypy`
- focused public and metadata regressions
- package validation via `scripts/package_check.py`
- release metadata validation via `scripts/release_metadata_check.py`
- the repository coverage gate
- the full pytest suite

## Tagging A Release

After local validation passes, create and push the version tag:

```bash
git tag v<version>
git push origin v<version>
```

The release workflow at `.github/workflows/release.yml` will:

1. Re-run repository validation.
2. Build the wheel and source distribution.
3. Upload the distribution artifacts.
4. Publish the GitHub release for the pushed tag, marking alpha, beta, and release-candidate tags as GitHub pre-releases.

## Post-Tag Verification

- Confirm the GitHub Actions release workflow completed successfully.
- Confirm the GitHub release includes both wheel and source-distribution artifacts.
- Confirm generated release notes align with `CHANGELOG.md` and the intended version scope.
- Confirm no release-blocking defects were discovered during the tagged workflow run.

## Release Gate Summary

Do not tag a release until all of the following are true:

- local release validation passes through `scripts/release_check.py`
- package artifacts install successfully from both wheel and sdist builds
- the coverage gate is passing
- plan and release-checklist mirrors are current
- changelog and migration notes are ready for the version being tagged