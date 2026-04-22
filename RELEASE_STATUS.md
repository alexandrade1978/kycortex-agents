# Release Status

This file tracks the current repository-owned release state for KYCortex after publication of the `1.0.13a6` alpha baseline and during refactor engineering on the current development head.

## Current State

- Package version in `pyproject.toml`: `1.0.13a10.dev0`
- Latest released version: `1.0.13a6`
- Release tag for this version: `not tagged (development head)`
- Most recent published release tag: `v1.0.13a6`
- Branch expected for release preparation: `main`
- Multi-model runtime routing is now implemented on the current head: primary-provider model candidates (`llm_model_candidates`) and ordered fallback-provider model sequences (`provider_fallback_models`) are both supported by runtime provider/model execution planning.
- Live multi-model smoke evidence now exists on the current head: a same-provider Ollama run with primary `qwen3.5:9b` and candidate `qwen2.5-coder:7b` completed successfully, with provider metadata showing transient failure on the first model and successful completion on the fallback model.
- Remote CI for the multi-model commit `270ad03` is green: GitHub Actions run `24781026643` completed with `success`.
- Current empirical requalification subset on `main`: `examples/example_release_user_smoke.py` passed on `openai`, `anthropic`, and local `ollama` with `qwen2.5-coder:7b` on 2026-04-22; `examples/example_provider_matrix_validation.py` also completed on all three providers (`openai`, `anthropic`, `ollama`) with `phase=completed` and `terminal_outcome=completed` for each provider workflow

## Refactor Engineering Suspension

- The current development head is in refactor-engineering mode and does not carry an active release, canary, or production-readiness claim.
- The last published and trusted release baseline remains `v1.0.13a6` on commit `f99a38d`.
- Historical canary evidence for the published `v1.0.13a6` line remains retained in the repository, but the branch is not currently advancing that canary window.
- A fresh release or canary claim is blocked until the refactor branch requalifies itself with deterministic validation gates and a new empirical baseline.
- The 2026-04-22 empirical subset is materially stronger after the matrix run but still not sufficient for a blanket new claim: the current head clears live smoke and matrix workflows on OpenAI, Anthropic, and Ollama with the maintained smaller local model, but the heavier local Ollama model `qwen3.5:9b` remains degraded (timeouts reproduced at 90s and 240s) and keeps the branch below full model-agnostic requalification.

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
- multi-model targeted regressions: passing (`tests/test_config.py` + `tests/test_base_agent.py`, including same-provider model fallback coverage)
- provider-focused integration regressions: passing (`tests/test_provider_agent_integration.py`, `tests/test_provider_metadata_accumulation.py`, `tests/test_provider_matrix.py`)
- focused public and metadata regressions: passing
- package validation: passing
- release metadata check: passing
- coverage gate: passing
- full pytest suite: passing

## Latest Published Release Verification

- `v1.0.13a6` is the current alpha release tag associated with the latest published repository-owned release state.
- The immediately preceding published state `v1.0.13a5` remains historical release evidence, but its canary bundle `docs/canary-evidence/c74e957/` is permanently retained as an abort record after the `release_user_smoke_ollama` code-validation incident.
- The published `v1.0.13a6` GitHub release now exposes the wheel, the source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json` together with GitHub's auto-generated source archives.
- Tagged Release workflow `#21` (`run 24324014556`) completed successfully on commit `f99a38d` for `v1.0.13a6`, re-ran the repository-owned release gate, validated the staged artifacts, generated and verified the release manifest, published the GitHub release, and verified the published asset set plus manifest-backed checksums after publication.
- The published GitHub release for `v1.0.13a6` was published at `2026-04-13T03:22:13Z` as a prerelease and attaches the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`.

## Current Release Validation Snapshot

- The release-validation snapshot below is historical evidence for the published `v1.0.13a6` line; it is not a release or canary claim for the current development head.

- The clean canonical Phase 15 rerun `full_matrix_validation_2026_04_12_v7` finished with 15 of 15 runs at `status=completed` and 15 of 15 runs at `terminal_outcome=completed` on the current candidate line.
- The local release-validation line re-cleared after the Phase 15 prompt hardening, including `ruff`, `mypy`, focused regressions, `scripts/release_metadata_check.py`, and `scripts/release_check.py`.
- The published `1.0.13a5` line correctly recorded the Phase 16 abort when `release_user_smoke_ollama` generated an artifact without `main()` and the persisted workflow state was rewritten to `failure_category=code_validation`.
- The published `1.0.13a6` line now injects a task-level public contract anchor into the `release-user-smoke` architecture, implementation, and review tasks so low-budget providers preserve the exact budget-planner API and CLI surface.
- Task public contract preflight on the published `1.0.13a6` line now normalizes annotated top-level function anchors and literal `__main__` guard requirements semantically instead of treating them as opaque strings, closing the false-negative mismatch exposed by the local Ollama rerun.
- Focused `release-user-smoke` regressions re-cleared on the reopened line: `tests/test_provider_matrix.py -k release_user_smoke` passed 7 of 7 tests.
- Focused orchestrator anchor regressions re-cleared on the reopened line: `tests/test_orchestrator.py -k task_public_contract_preflight_accepts_annotated_function_anchor or build_code_validation_summary_includes_task_public_contract_preflight` passed 2 of 2 tests.
- Local release validation re-cleared on the published line: `python scripts/release_check.py` completed successfully with the full 1216-test suite green and the coverage gate still above the required threshold.
- A live local Ollama rerun of `examples/example_release_user_smoke.py` on the repaired line completed successfully with artifact validation passing and sample balance `2650.00`.
- Tagged Release workflow `#21` re-ran the repository-owned release gate, built the wheel and source distribution, validated the staged artifacts, generated and verified `release-artifact-manifest.json`, generated `release-promotion-summary.json`, published the GitHub release, and re-verified the published assets and checksums.
- The strongest current full provider-matrix checkpoint `output/provider_matrix_validation_step3o` completed for Anthropic, Ollama, and OpenAI on the current maintenance branch.
- Dedicated provider reruns `output/provider_matrix_validation_step3n_anthropic` and `output/provider_matrix_validation_step3n_ollama` both completed with `repair_cycle_count=0` after the latest repair-routing hardening.
- The focused empirical rerun `output/provider_matrix_validation_step3r_openai` completed with `repair_cycle_count=0`, closing the remaining residual OpenAI repair observed after `step3q`.
- Public docs and examples now align on the validated local Ollama baseline `qwen2.5-coder:7b` with `ollama_num_ctx=16384`, using explicit HTTP endpoint overrides when the runtime is not exposed at the default local URL.
- Clean-environment GitHub Actions validation is restored after the provider-matrix budget regression test was updated to inject its own fake OpenAI credential instead of depending on ambient developer-shell secrets.
- The live local smoke run `output/release_user_smoke_ollama_live` completed with `repair_cycle_count=0`, and a clean-install smoke of the released package also generated a valid artifact against the same local Ollama runtime.
- The `v1.0.13a8` fix adds typed `detail_fixture_example` dicts to each `ScenarioSpec` in the campaign script, replacing the generic `{'field_one': 'value'}` placeholder that the LLM was copying verbatim into test fixtures, causing `TypeError: '>' not supported between instances of 'str' and 'int'`.
- Campaign `v63_openai_returns_typed_fixture` validated `returns_abuse_screening` with OpenAI gpt-4o-mini: `status=completed`, 7/7 tasks done, 0 repair cycles, 86s — previously always failed with `test_validation` after 3 repair cycles.
- Updated baseline: OpenAI 5/5, Anthropic 5/5, Ollama 4/5 = 14/15 total (up from 13/15).

## Current Canary Status

- There is no active canary claim on the current development head.
- The last published `v1.0.13a6` Phase 16 evidence remains retained as historical published-line evidence while refactor engineering is in progress.
- Historical Phase 16 canary evidence for the published `v1.0.13a3` line remains closed as an abort record at `docs/canary-evidence/2563383/` after `run_06_ollama` triggered a zero-budget false success.
- Historical Phase 16 canary evidence for the published `v1.0.13a4` line remains closed as an abort record at `docs/canary-evidence/8bfdc29/` after `run_04_openai` triggered a code-validation incident.
- Historical Phase 16 canary evidence for the previously published `v1.0.13a5` line remains closed as an abort record at `docs/canary-evidence/c74e957/` after `release_user_smoke_ollama` triggered a code-validation incident.
- Historical Phase 16 canary traffic for the published `v1.0.13a6` line opened on `2026-04-13T03:25:21Z` after OpenAI, Anthropic, and Ollama all reported healthy preflight provider status in the live kickoff bundle.
- The first controlled workflow `release_user_smoke_openai` was externally validated and accepted at `2026-04-13T03:26:22.839835+00:00`, refreshed expansion provider health at `2026-04-13T03:51:37.043973+00:00`, `2026-04-13T04:03:29.889609+00:00`, `2026-04-13T04:15:41.775710+00:00`, `2026-04-13T09:22:33.389958+00:00`, and `2026-04-13T09:41:39.329840+00:00` kept OpenAI, Anthropic, and Ollama healthy before continued same-day admission and the run-100 push, and no provider-health incident occurred during expansion.
- The clean checkpoint through run 100 completed at `2026-04-13T10:39:05.274887+00:00` with 100 eligible workflows seen, 100 accepted workflows, 0 incidents, 0 rollback actions, and provider breakdown OpenAI 34, Anthropic 33, Ollama 33.
- The first same-day daily review was recorded at `2026-04-13T04:30:01.447970+00:00` and confirmed the window remains within the current policy envelope.
- The retained Phase 16 evidence bundle remains tracked at `docs/canary-evidence/f99a38d/` for the published tag `v1.0.13a6`.
- The rollback baseline `v1.0.13a2` remains the approved safe target, and no live cutover has been required.

## Release Outcome

The 1.0.13a6 alpha release is now captured directly in the package metadata, changelog, release guide, release-check workflow inputs, and the published GitHub release evidence.

The current development head is not a published release candidate. It is an explicit refactor branch that must earn a fresh release and canary claim after requalification.

The repository's public licensing guidance continues to document the AGPL open-source distribution together with a separate commercial licensing path.

The current alpha branch now documents and validates explicit Ollama runtime overrides, the dedicated local Ollama empirical baseline, stronger QA/test repair constraints, code-repair routing that consumes the failing pytest suite as concrete repair evidence, deterministic clean-environment CI validation for the provider-matrix budget regression surface, a user-style live release smoke path, and the active Phase 16 canary evidence bundle for `f99a38d` through a clean 100-workflow checkpoint plus the first same-day daily review.

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

For the current development head in refactor-engineering mode:

1. complete the documentation and version truth reset for the refactor branch
2. begin the low-risk orchestrator refactor by extracting deterministic infrastructure and internal interfaces
3. re-open targeted validation only after deterministic gates are green, then collect a fresh empirical baseline before any new release or canary claim