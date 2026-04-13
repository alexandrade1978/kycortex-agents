# Release Status

This file tracks the current repository-owned release state for KYCortex while preparing the 1.0.13a5 alpha maintenance release after publication of the 1.0.13a4 alpha release.

## Current State

- Package version in `pyproject.toml`: `1.0.13a5`
- Latest released version: `1.0.13a4`
- Release tag for this version: `v1.0.13a5`
- Most recent published release tag: `v1.0.13a4`
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

- `v1.0.13a4` is the current alpha release tag associated with the latest published repository-owned release state.
- The immediately preceding published state `v1.0.13a3` remains historical release evidence, but it is permanently disqualified for canary continuation and rollback promotion by the zero-budget false-success incident captured in `docs/canary-evidence/2563383/`.
- The published `v1.0.13a4` GitHub release now exposes the wheel, the source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json` together with GitHub's auto-generated source archives.
- GitHub Actions run `#460` completed successfully on commit `8bfdc29`, and tagged Release workflow `#19` completed successfully for `v1.0.13a4` on the same published candidate line.
- The published `release-promotion-summary.json` binds `v1.0.13a4` to commit `8bfdc29516df09ccce0488352f5246b1d9be1091` with `manifest_verified=true`, and the published wheel plus source distribution match the attached manifest checksums.

## Current Release Validation Snapshot

- The clean canonical Phase 15 rerun `full_matrix_validation_2026_04_12_v7` finished with 15 of 15 runs at `status=completed` and 15 of 15 runs at `terminal_outcome=completed` on the current candidate line.
- The local release-validation line re-cleared after the Phase 15 prompt hardening, including `ruff`, `mypy`, focused regressions, `scripts/release_metadata_check.py`, and `scripts/release_check.py`.
- The current `1.0.13a4` maintenance line now rewrites deterministic `release-user-smoke` artifact-validation failures back into persisted workflow state as `code_validation` workflow failures, closing the false-success path that allowed a generated artifact without `main()` to remain recorded as accepted.
- The reopened `1.0.13a5` maintenance line now also rejects unsupported non-standard-library imports deterministically during `release-user-smoke` artifact validation and reinforces the standard-library-only contract across architecture, implementation, and review prompts.
- Focused `release-user-smoke` regressions re-cleared on the reopened line: `tests/test_provider_matrix.py -k release_user_smoke` passed 5 of 5 tests.
- Local remediation validation re-cleared on the fix line: `tests/test_provider_matrix.py` passed 54 of 54 tests, and `python scripts/release_check.py` completed successfully with the full 1211-test suite green and the coverage gate still above the required threshold.
- GitHub Actions CI also re-cleared on remediation commit `e23c1f7`, confirming the false-success fix, regression coverage, and release-status updates on the `1.0.13a4` maintenance line.
- GitHub Actions run `#460` completed successfully on commit `8bfdc29`, and tagged Release workflow `#19` completed successfully for `v1.0.13a4` on the same published candidate line.
- The published `v1.0.13a4` release packet now includes repository-owned artifact provenance through `release-artifact-manifest.json` and `release-promotion-summary.json`, both verified against the published assets.
- The strongest current full provider-matrix checkpoint `output/provider_matrix_validation_step3o` completed for Anthropic, Ollama, and OpenAI on the current maintenance branch.
- Dedicated provider reruns `output/provider_matrix_validation_step3n_anthropic` and `output/provider_matrix_validation_step3n_ollama` both completed with `repair_cycle_count=0` after the latest repair-routing hardening.
- The focused empirical rerun `output/provider_matrix_validation_step3r_openai` completed with `repair_cycle_count=0`, closing the remaining residual OpenAI repair observed after `step3q`.
- Public docs and examples now align on the validated local Ollama baseline `qwen2.5-coder:7b` with `ollama_num_ctx=16384`, using explicit HTTP endpoint overrides when the runtime is not exposed at the default local URL.
- Clean-environment GitHub Actions validation is restored after the provider-matrix budget regression test was updated to inject its own fake OpenAI credential instead of depending on ambient developer-shell secrets.
- The live local smoke run `output/release_user_smoke_ollama_live` completed with `repair_cycle_count=0`, and a clean-install smoke of the released package also generated a valid artifact against the same local Ollama runtime.

## Current Canary Status

- Historical Phase 16 canary evidence for the published `v1.0.13a3` line remains closed as an abort record at `docs/canary-evidence/2563383/` after `run_06_ollama` triggered a zero-budget false success.
- Fresh Phase 16 canary traffic for the published `v1.0.13a4` line opened on `2026-04-13T00:56:30Z` after OpenAI, Anthropic, and Ollama all reported healthy preflight provider status at `2026-04-13T00:56:52.840533Z`.
- Provider health was refreshed before expansion at `2026-04-13T01:28:52.992574Z`, and the first 3 controlled workflows validated cleanly across OpenAI, Anthropic, and Ollama by `2026-04-13T01:33:54.386905+00:00`.
- The fourth controlled workflow `run_04_openai` then failed external artifact validation at `2026-04-13T01:34:53.543209+00:00`, and the persisted state correctly recorded `phase=failed`, `terminal_outcome=failed`, `failure_category=code_validation`, and `acceptance_criteria_met=false` because importing the generated module raised `ModuleNotFoundError: No module named 'click'`.
- The `docs/canary-evidence/8bfdc29/` window is therefore aborted and expansion is frozen at 4 eligible workflows because accepted workflow rate fell to `75.0%`, missed the canary SLO, and triggered rollback policy.
- The rollback baseline `v1.0.13a2` remains the approved safe target, and no broader live cutover was required because traffic never advanced beyond the controlled subset.

## Release Outcome

The 1.0.13a4 alpha release is now captured directly in the package metadata, changelog, release guide, release-check workflow inputs, and the published GitHub release evidence.

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

For the reopened `1.0.13a5` maintenance line:

1. rerun the repository release gates on `1.0.13a5`, including release metadata validation and the full release check
2. cut and publish a fresh `v1.0.13a5` candidate only after the reopened line re-clears the release gates
3. keep the rollback target pinned to `v1.0.13a2` and restart Phase 16 from fresh preflight on the new candidate rather than resuming `v1.0.13a4`