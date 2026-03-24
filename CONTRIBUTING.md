# Contributing

## Development Setup

1. Clone the repository.
2. Create or activate a Python 3.10+ environment.
3. Install the editable development environment:

```bash
pip install -e ".[test]"
```

If you prefer command aliases for the common local workflow, the repository also includes a `Makefile`:

```bash
make setup
make install-hooks
```

## Workflow

1. Make a focused change.
2. Add or update tests for the behavior you changed.
3. Run the relevant test subset locally.
4. Run the full test suite before opening a pull request.

### Suggested Test Commands

- Install the repository hook automation locally:

```bash
python -m pre_commit install --install-hooks --hook-type pre-commit --hook-type pre-push
make install-hooks
```

- Run the full pre-commit automation locally before pushing:

```bash
python -m pre_commit run --all-files
python -m pre_commit run --all-files --hook-stage pre-push
make precommit
make prepush
```

- Validate built package artifacts locally before publishing:

```bash
python scripts/package_check.py
make package-check
```

- Trigger the repository release workflow after local validation:

```bash
python -m pytest -q
git tag v<version>
git push origin v<version>
```

- Use `.github/workflows/release.yml` for manual `workflow_dispatch` dry runs and for tagged GitHub releases that attach built wheel and source-distribution artifacts.
- Use `RELEASE.md` for the full repository-owned release validation, tagging, and post-tag verification procedure.
- Use `RELEASE_STATUS.md` for the current repository-owned release-readiness snapshot before making a tagging decision.

- Local lint and type-check baseline:

```bash
python -m ruff check .
python -m mypy
make lint
make typecheck
```

- Coverage gate used by the release-readiness workflow:

```bash
python -m pytest --cov=kycortex_agents --cov-report=term-missing --cov-report=xml -q
make coverage
```

- Release metadata and version-alignment check before tagging:

```bash
python scripts/release_metadata_check.py
make release-metadata-check
```

- Full release validation before tagging a version:

```bash
python scripts/release_check.py
make release-check
```

- Public API or import-surface changes:

```bash
python -m pytest tests/test_public_api.py tests/test_public_smoke.py -q
make test-public
```

- Packaging, metadata, or documentation contract changes:

```bash
python -m pytest tests/test_package_metadata.py -q
make test-metadata
```

- Full repository validation before opening a pull request:

```bash
python -m pytest -q
make test
```

## Local Tooling

- `Makefile`: convenient aliases for setup and the main validation commands.
- `.editorconfig`: shared line-ending, indentation, and trailing-whitespace defaults for Python, Markdown, TOML, YAML, and Makefile edits.
- `.pre-commit-config.yaml`: repository-local pre-commit and pre-push automation for linting, type checking, and focused public-surface regressions.
- `scripts/package_check.py`: local built-artifact validator that builds both wheel and source distributions, installs them into temporary virtual environments, and smoke-tests the public package imports.
- `scripts/release_metadata_check.py`: local release-metadata validator that checks package version alignment, release-state metadata, and release-facing documentation cues before a tag is created.
- `scripts/release_check.py`: local release validator that runs the repository lint, type-check, focused regression, package-validation, coverage-gate, and full-suite commands in the same order used for release readiness.
- `.github/workflows/release.yml`: tagged-release automation that reruns validation, builds wheel and source distributions, uploads them as workflow artifacts, and publishes them on GitHub releases for `v*` tags.
- `coverage.py` and `pytest-cov`: repository-owned coverage gate tooling configured through `pyproject.toml` and exercised in both local validation and GitHub Actions.
- `ruff`: repository lint baseline for the package, examples, tests, and docs-adjacent Python files.
- `mypy`: local type-check baseline for `kycortex_agents` and `examples`, with third-party `anthropic` imports excluded from stub enforcement.
- `pre-commit`: local hook runner that executes the repository-owned `ruff`, `mypy`, and focused pytest checks before commits and pushes.
- `.github/workflows/ci.yml`: GitHub Actions baseline that runs linting, type checking, focused public-surface regressions, and the full pytest suite on pull requests and pushes to `main`.

## Pull Requests

1. Keep changes small and scoped to one concern.
2. Update documentation when public behavior or usage changes.
3. Preserve backward compatibility unless the change explicitly updates the public contract.
4. Include a clear summary of the problem, the fix, and the validation you ran.

## Contribution Licensing

- The public repository is distributed under AGPL-3.0. See [LICENSE](LICENSE).
- KYCortex may also distribute the codebase under separate commercial terms. See [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).
- See [CONTRIBUTOR_RIGHTS.md](CONTRIBUTOR_RIGHTS.md) for the repository's contributor-rights policy under the dual-license model.
- If a contribution is intended to ship in a dual-licensed commercial distribution, maintainers may review contributor rights on a case-by-case basis and request an explicit written rights grant when needed.
- If you contribute on behalf of an employer or client, make sure you have the authority to submit that contribution.

## Quality Expectations

- Keep all repository content in English.
- Prefer minimal, well-tested changes over broad refactors.
- Do not commit generated build artifacts or local environment files.