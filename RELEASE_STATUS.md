# Release Status

This file tracks the current repository-owned release state for KYCortex during preparation of the 1.0.11 maintenance release.

## Current State

- Package version in `pyproject.toml`: `1.0.11`
- Latest released version: `1.0.11`
- Release tag for this version: `v1.0.11`
- Branch expected for release preparation: `main`

## Repository Release Gates

- Local release validation is available through `python scripts/release_check.py` and `make release-check`.
- Built package artifacts are validated through `scripts/package_check.py`.
- Release metadata alignment is validated through `python scripts/release_metadata_check.py` and `make release-metadata-check`.
- Repository coverage is enforced through the `pytest-cov` gate configured in `pyproject.toml`.
- Tagged release automation is defined in `.github/workflows/release.yml`.
- Changelog and migration guidance are maintained in `CHANGELOG.md` and `MIGRATION.md`.

## Latest Validated Release-Readiness Pass

- `ruff`: passing
- `mypy`: passing
- focused public and metadata regressions: passing
- package validation: passing
- release metadata check: passing
- coverage gate: passing
- full pytest suite: passing

## Latest Published Release Verification

- `v1.0.11` is the current release tag associated with this repository-owned release state.
- The immediately preceding published state `v1.0.10` is now the previous maintenance baseline.
- Expected attached assets remain `kycortex_agents-1.0.11-py3-none-any.whl` and `kycortex_agents-1.0.11.tar.gz`.

## Current Release Validation Snapshot

- The strongest current full provider-matrix checkpoint `output/provider_matrix_validation_step3o` completed for Anthropic, Ollama, and OpenAI on the current maintenance branch.
- Dedicated provider reruns `output/provider_matrix_validation_step3n_anthropic` and `output/provider_matrix_validation_step3n_ollama` both completed with `repair_cycle_count=0` after the latest repair-routing hardening.
- Public docs and examples now align on the validated local Ollama baseline `qwen2.5-coder:7b` with `ollama_num_ctx=16384`, using explicit HTTP endpoint overrides when the runtime is not exposed at the default local URL.

## Release Outcome

The 1.0.11 maintenance-development state is now captured directly in the package metadata, changelog, release guide, and release-check workflow inputs.

The repository's public licensing guidance continues to document the AGPL open-source distribution together with a separate commercial licensing path.

The current maintenance branch now documents and validates explicit Ollama runtime overrides, the dedicated local Ollama empirical baseline, stronger QA/test repair constraints, and code-repair routing that consumes the failing pytest suite as concrete repair evidence.

Use the following repository-owned references when validating follow-up maintenance releases:

- `COMMERCIAL_LICENSE.md`
- `RELEASE.md`
- `.local-docs/release-checklist.md`
- `CHANGELOG.md`
- `MIGRATION.md`

## Next Maintenance Action

For future tagged releases:

1. update the package version for the intended release
2. rerun `python scripts/release_check.py`
3. create and push the matching `v<version>` tag
4. verify the tagged GitHub release workflow and attached artifacts