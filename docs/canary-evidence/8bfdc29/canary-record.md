# Canary Record - 8bfdc29

Status: aborted after code-validation incident on `run_04_openai`

This record opens the candidate evidence bundle for released commit `8bfdc29516df09ccce0488352f5246b1d9be1091` and tag `v1.0.13a4`.

The live Phase 16 window started on `2026-04-13T00:56:30Z` on the maintainer-operated host `alex-kycortex`.

The window was aborted on `2026-04-13T01:34:53.543209+00:00` after `run_04_openai` generated a Python artifact that imported `click`, causing external artifact validation to fail with `ModuleNotFoundError: No module named 'click'`. The incident preserved bounded termination, but it dropped accepted workflow rate to `75.0%`, missed the canary SLO, and triggered rollback policy.

## Candidate Identity

- candidate commit SHA: `8bfdc29516df09ccce0488352f5246b1d9be1091`
- candidate commit subject: `Record rollback baseline smoke evidence`
- release tag: `v1.0.13a4`
- branch at release cut: `main`
- package version: `1.0.13a4`
- signature state: GitHub verified commit and verified tag
- supporting GitHub Actions CI run: `#460` (`completed/success`)
- supporting GitHub Actions Release run: `#19` (`completed/success`)
- immediately preceding published alpha: `v1.0.13a3` (historical release only; not approved for rollback or resumed canary use)

## Current Owner Binding

| Role | Current named owner | Contact path |
| --- | --- | --- |
| Release owner | Alexandre Andrade | `alex@kycortex.com` |
| Canary operator | Alexandre Andrade | `alex@kycortex.com` |
| Support responder | Alexandre Andrade | `alex@kycortex.com` |
| Security responder | Alexandre Andrade | `alex@kycortex.com` |

## Rollback Target

- rollback target SHA: `b2dc9931d12c5d31651a97bba8c99e767b582ff8`
- rollback target role: previous known-good alpha release `v1.0.13a2`
- rollback smoke status for the live canary environment: re-smoke validated at `2026-04-13T00:18:27.996254+00:00` via controlled Ollama `release-user-smoke`; evidence retained in `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`

## Canary Scope

- deployment class: single-maintainer pre-production canary
- environment identifier: `alex-kycortex` native Linux maintainer host (`Linux-6.17.0-20-generic-x86_64-with-glibc2.39`)
- eligible workflow classes: controlled `release-user-smoke` workflows on OpenAI `gpt-4o-mini`, Anthropic `claude-haiku-4-5-20251001`, and Ollama `qwen2.5-coder:7b`
- canary start time: `2026-04-13T00:56:30Z`
- minimum evidence window: at least 7 consecutive days or 100 eligible workflows, whichever is later

## Current State

- release-candidate gate evidence exists for the current published release line, and GitHub release `v1.0.13a4` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`
- historical abort evidence for the disqualified `v1.0.13a3` line is retained under `../2563383/`
- preflight provider health captured at `2026-04-13T00:56:52.840533Z` recorded OpenAI, Anthropic, and Ollama as healthy before traffic
- expansion provider health refreshed at `2026-04-13T01:28:52.992574Z` recorded OpenAI, Anthropic, and Ollama as healthy before broader admission
- the first 3 controlled workflows `release_user_smoke_openai`, `release_user_smoke_anthropic`, and `release_user_smoke_ollama` were externally validated and accepted by `2026-04-13T01:33:54.386905+00:00`
- the fourth controlled workflow `run_04_openai` finished `failed` with `failure_category=code_validation` after external artifact validation rejected `artifacts/code_implementation.py` because importing the generated module raised `ModuleNotFoundError: No module named 'click'`
- the canary was aborted and expansion frozen at 4 eligible workflows because accepted workflow rate fell to `75.0%`, missed the `>=95.0%` canary SLO, and consumed more than half of the allowed non-zero accepted-workflow budget in the first half of the observation window
- no broader customer-facing traffic remained to drain, so the rollback decision froze further admission without requiring a live cutover away from the controlled subset
- live checkpoint exports from `snapshot()` and `internal_runtime_telemetry()` have been captured for the first accepted workflow and the aborting code-validation incident checkpoint

## Evidence References

- Phase 16 operations guide: `../canary-operations.md`
- repository evidence-root rules: `../README.md`
- current candidate parity and checkpoint record: `environment-parity.md`, `provider-health.json`, `workflow-summary.json`, `internal-runtime-telemetry.json`
- retained canary validation artifacts: `validation-artifacts/preflight-provider-health-2026-04-13T00-56-52Z.json`, `validation-artifacts/checkpoint-first-accepted-2026-04-13T00-57-23Z.json`, `validation-artifacts/expansion-provider-health-2026-04-13T01-28-52Z.json`, `validation-artifacts/checkpoint-through-run-04-2026-04-13T01-34-53Z.json`
- retained rollback evidence for the approved rollback target: `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`
- retained release evidence: Phase 15 canonical matrix `full_matrix_validation_2026_04_12_v7`, GitHub Actions run `#460`, GitHub Actions Release run `#19`, and GitHub release `v1.0.13a4`