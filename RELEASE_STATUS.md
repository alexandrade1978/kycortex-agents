# Release Status

This file tracks the current repository-owned release state for KYCortex after publication of the 1.0.13a5 alpha maintenance release.

## Current State

- Package version in `pyproject.toml`: `1.0.13a5`
- Latest released version: `1.0.13a5`
- Release tag for this version: `v1.0.13a5`
- Most recent published release tag: `v1.0.13a5`
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

- `v1.0.13a5` is the current alpha release tag associated with the latest published repository-owned release state.
- The immediately preceding published state `v1.0.13a4` remains historical release evidence, but its canary bundle `docs/canary-evidence/8bfdc29/` is permanently retained as an abort record after the `run_04_openai` code-validation incident.
- The published `v1.0.13a5` GitHub release now exposes the wheel, the source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json` together with GitHub's auto-generated source archives.
- Tagged Release workflow `#20` (`run 24322816456`) completed successfully on commit `c74e957` for `v1.0.13a5`, re-ran the repository-owned release gate, and verified the published asset set and manifest-backed checksums after publication.
- The published `release-promotion-summary.json` binds `v1.0.13a5` to commit `c74e957ae76e9605d21b91ccc6d36bd1f25be16c` with `manifest_verified=true`, and the published wheel plus source distribution match the attached manifest checksums.

## Current Release Validation Snapshot

- The clean canonical Phase 15 rerun `full_matrix_validation_2026_04_12_v7` finished with 15 of 15 runs at `status=completed` and 15 of 15 runs at `terminal_outcome=completed` on the current candidate line.
- The local release-validation line re-cleared after the Phase 15 prompt hardening, including `ruff`, `mypy`, focused regressions, `scripts/release_metadata_check.py`, and `scripts/release_check.py`.
- The published `1.0.13a5` line rejects unsupported non-standard-library imports deterministically during `release-user-smoke` artifact validation and reinforces the standard-library-only contract across architecture, implementation, and review prompts.
- Focused `release-user-smoke` regressions re-cleared on the published line: `tests/test_provider_matrix.py -k release_user_smoke` passed 5 of 5 tests.
- Local release validation re-cleared on the published line: `python scripts/release_check.py` completed successfully with the full 1213-test suite green and the coverage gate still above the required threshold.
- Tagged Release workflow `#20` re-ran the repository-owned release gate, built the wheel and source distribution, validated the staged artifacts, generated and verified `release-artifact-manifest.json`, generated `release-promotion-summary.json`, published the GitHub release, and re-verified the published assets and checksums.
- The strongest current full provider-matrix checkpoint `output/provider_matrix_validation_step3o` completed for Anthropic, Ollama, and OpenAI on the current maintenance branch.
- Dedicated provider reruns `output/provider_matrix_validation_step3n_anthropic` and `output/provider_matrix_validation_step3n_ollama` both completed with `repair_cycle_count=0` after the latest repair-routing hardening.
- The focused empirical rerun `output/provider_matrix_validation_step3r_openai` completed with `repair_cycle_count=0`, closing the remaining residual OpenAI repair observed after `step3q`.
- Public docs and examples now align on the validated local Ollama baseline `qwen2.5-coder:7b` with `ollama_num_ctx=16384`, using explicit HTTP endpoint overrides when the runtime is not exposed at the default local URL.
- Clean-environment GitHub Actions validation is restored after the provider-matrix budget regression test was updated to inject its own fake OpenAI credential instead of depending on ambient developer-shell secrets.
- The live local smoke run `output/release_user_smoke_ollama_live` completed with `repair_cycle_count=0`, and a clean-install smoke of the released package also generated a valid artifact against the same local Ollama runtime.

## Current Canary Status

- Historical Phase 16 canary evidence for the published `v1.0.13a3` line remains closed as an abort record at `docs/canary-evidence/2563383/` after `run_06_ollama` triggered a zero-budget false success.
- Historical Phase 16 canary evidence for the published `v1.0.13a4` line remains closed as an abort record at `docs/canary-evidence/8bfdc29/` after `run_04_openai` triggered a code-validation incident.
- Fresh Phase 16 canary traffic for the published `v1.0.13a5` line opened on `2026-04-13T02:34:33Z` after OpenAI, Anthropic, and Ollama all reported healthy preflight provider status at `2026-04-13T02:34:45.948542+00:00`.
- The first controlled `release_user_smoke_openai` checkpoint admitted 1 eligible workflow on the live maintainer-operated canary host and externally validated it successfully on OpenAI at `2026-04-13T02:35:04.405705+00:00`.
- The active canary window now lives under `docs/canary-evidence/c74e957/` and remains intentionally frozen at the smallest controlled subset until the next explicit expansion checkpoint.
- The rollback baseline `v1.0.13a2` remains the approved safe target, and no rollback action has been required in the current `v1.0.13a5` window.

## Release Outcome

The 1.0.13a5 alpha release is now captured directly in the package metadata, changelog, release guide, release-check workflow inputs, and the published GitHub release evidence.

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

For the active published `1.0.13a5` release line:

1. continue collecting Phase 16 evidence in `docs/canary-evidence/c74e957/` through the next explicit checkpoint
2. refresh provider health, workflow summaries, internal runtime telemetry, and validation artifacts before any canary expansion beyond the first accepted workflow
3. keep the rollback target pinned to `v1.0.13a2` until the active canary window closes cleanly