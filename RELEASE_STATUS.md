# Release Status

This file tracks the current repository-owned release state for KYCortex during preparation of the 1.0.13a4 alpha release.

## Current State

- Package version in `pyproject.toml`: `1.0.13a4`
- Latest released version: `1.0.13a3`
- Release tag for this version: `v1.0.13a4`
- Most recent published release tag: `v1.0.13a3`
- Branch expected for release preparation: `main`

## Repository Release Gates

- Local release validation is available through `python scripts/release_check.py` and `make release-check`.
- Built package artifacts are validated through `scripts/package_check.py`.
- The exact staged release artifacts are smoke-validated through `python scripts/package_check.py --dist-dir dist` in the tagged release workflow.
- Staged artifact-promotion evidence is generated and verified through `python scripts/release_artifact_manifest.py` in the tagged release workflow.
- Release promotion provenance is written through `python scripts/release_promotion_summary.py` after manifest verification in the tagged release workflow.
- Published GitHub release assets are downloaded and verified through `python scripts/release_published_assets_check.py` after the tagged workflow publishes the release.
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

- `v1.0.13a3` is the current alpha release tag associated with the latest published repository-owned release state.
- The immediately preceding published state `v1.0.13a2` is now the previous alpha baseline.
- The next tagged release workflow is expected to attach `kycortex_agents-1.0.13a4-py3-none-any.whl`, `kycortex_agents-1.0.13a4.tar.gz`, `release-artifact-manifest.json`, and `release-promotion-summary.json`.
- The published `v1.0.13a3` GitHub release now exposes the wheel, the source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json` together with GitHub's auto-generated source archives.
- The same tagged workflow now verifies through the GitHub API that the published release exposes exactly that attached asset set and that the downloaded wheel and source distribution match the attached manifest checksums.

## Current Release Validation Snapshot

- The clean canonical Phase 15 rerun `full_matrix_validation_2026_04_12_v7` finished with 15 of 15 runs at `status=completed` and 15 of 15 runs at `terminal_outcome=completed` on the current candidate line.
- The local release-validation line re-cleared after the Phase 15 prompt hardening, including `ruff`, `mypy`, focused regressions, `scripts/release_metadata_check.py`, and `scripts/release_check.py`.
- The current `1.0.13a4` maintenance line now rewrites deterministic `release-user-smoke` artifact-validation failures back into persisted workflow state as `code_validation` workflow failures, closing the false-success path that allowed a generated artifact without `main()` to remain recorded as accepted.
- Local remediation validation re-cleared on the fix line: `tests/test_provider_matrix.py` passed 54 of 54 tests, and `python scripts/release_check.py` completed successfully with the full 1211-test suite green and the coverage gate still above the required threshold.
- GitHub Actions run `#456` completed successfully on commit `2563383`, and tagged Release workflow `#18` completed successfully for `v1.0.13a3` on the same published candidate line.
- The strongest current full provider-matrix checkpoint `output/provider_matrix_validation_step3o` completed for Anthropic, Ollama, and OpenAI on the current maintenance branch.
- Dedicated provider reruns `output/provider_matrix_validation_step3n_anthropic` and `output/provider_matrix_validation_step3n_ollama` both completed with `repair_cycle_count=0` after the latest repair-routing hardening.
- The focused empirical rerun `output/provider_matrix_validation_step3r_openai` completed with `repair_cycle_count=0`, closing the remaining residual OpenAI repair observed after `step3q`.
- Public docs and examples now align on the validated local Ollama baseline `qwen2.5-coder:7b` with `ollama_num_ctx=16384`, using explicit HTTP endpoint overrides when the runtime is not exposed at the default local URL.
- Clean-environment GitHub Actions validation is restored after the provider-matrix budget regression test was updated to inject its own fake OpenAI credential instead of depending on ambient developer-shell secrets.
- The live local smoke run `output/release_user_smoke_ollama_live` completed with `repair_cycle_count=0`, and a clean-install smoke of the released package also generated a valid artifact against the same local Ollama runtime.

## Current Canary Status

- Phase 16 canary traffic for the published `v1.0.13a3` line opened on `2026-04-12T23:13:35.578054Z` after OpenAI, Anthropic, and Ollama all reported healthy preflight provider status.
- The controlled `release-user-smoke` checkpoint admitted 6 eligible workflows on the live maintainer-operated canary host and externally validated 5 of them successfully.
- `run_06_ollama` triggered a zero-budget false success: the workflow reached `completed` with `acceptance_criteria_met=true`, but the generated artifact omitted the required `main()` entrypoint.
- The canary window is therefore aborted and further traffic is frozen until the defect is fixed, the rollback baseline is re-smoke-validated, and a fresh candidate restarts Phase 16.
- The maintenance line now contains the local fix and regression coverage for that contract, but the published `v1.0.13a3` canary record remains historical evidence of the aborted attempt; no fresh candidate has been cut yet and Phase 16 has not restarted.

## Release Outcome

The 1.0.13a4 alpha-candidate state is now captured directly in the package metadata, changelog, release guide, and release-check workflow inputs, while `1.0.13a3` remains the latest released alpha tag.

The repository's public licensing guidance continues to document the AGPL open-source distribution together with a separate commercial licensing path.

The current alpha branch now documents and validates explicit Ollama runtime overrides, the dedicated local Ollama empirical baseline, stronger QA/test repair constraints, code-repair routing that consumes the failing pytest suite as concrete repair evidence, deterministic clean-environment CI validation for the provider-matrix budget regression surface, and a user-style live release smoke path.

The current alpha branch now also stages release artifact-promotion evidence through `release-artifact-manifest.json`, generated and verified in the tagged release workflow before publication.

The same tagged workflow now records a repository-owned `release-promotion-summary.json` packet that ties the verified manifest checksum to the pushed tag, commit SHA, and promoted wheel and source distribution.

The same staged workflow now smoke-validates the exact promoted wheel and source distribution before any release metadata is attached or published.

The same tagged workflow now also downloads the published GitHub release assets and verifies their list, sizes, and manifest-backed checksums through `scripts/release_published_assets_check.py` immediately after publication.

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
4. verify the tagged GitHub release workflow, staged artifact smoke validation, attached artifacts, `release-artifact-manifest.json`, `release-promotion-summary.json`, and the published-asset checksum verification step