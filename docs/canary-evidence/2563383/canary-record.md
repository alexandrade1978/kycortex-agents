# Canary Record - 2563383

Status: aborted after zero-budget false-success incident

This record opened the candidate evidence bundle for released commit `25633830213afd029418b2a856e097b2403edc4f` and tag `v1.0.13a3`.

The live Phase 16 window started on `2026-04-12T23:13:35.578054Z` on the maintainer-operated host `alex-kycortex`.

The window was aborted on `2026-04-12T23:16:16.292317+00:00` after `run_06_ollama` produced a zero-budget false success: the workflow finished `completed` with `acceptance_criteria_met=true`, but the externally validated generated artifact omitted the required `main()` entrypoint.

## Candidate Identity

- candidate commit SHA: `25633830213afd029418b2a856e097b2403edc4f`
- candidate commit subject: `Prepare 1.0.13a3 alpha`
- release tag: `v1.0.13a3`
- branch at release cut: `main`
- package version: `1.0.13a3`
- signature state: GitHub verified commit and verified tag
- supporting GitHub Actions CI run: `#456` (`completed/success`)
- supporting GitHub Actions Release run: `#18` (`completed/success`)
- previous published alpha baseline: `v1.0.13a2`

## Current Owner Binding

| Role | Current named owner | Contact path |
| --- | --- | --- |
| Release owner | Alexandre Andrade | `alex@kycortex.com` |
| Canary operator | Alexandre Andrade | `alex@kycortex.com` |
| Support responder | Alexandre Andrade | `alex@kycortex.com` |
| Security responder | Alexandre Andrade | `alex@kycortex.com` |

## Rollback Target

- rollback target SHA: `b2dc9931d12c5d31651a97bba8c99e767b582ff8`
- rollback target role: previous published alpha release `v1.0.13a2`
- rollback smoke status for the live canary environment: not executed after abort; any resumed canary must restart from `v1.0.13a2`

## Canary Scope

- deployment class: single-maintainer pre-production canary
- environment identifier: `alex-kycortex` native Linux maintainer host (`Linux-6.17.0-20-generic-x86_64-with-glibc2.39`)
- eligible workflow classes: controlled `release-user-smoke` workflows on OpenAI `gpt-4o-mini`, Anthropic `claude-haiku-4-5-20251001`, and Ollama `qwen2.5-coder:7b`
- canary start time: `2026-04-12T23:13:35.578054Z`
- minimum evidence window: at least 7 consecutive days or 100 eligible workflows, whichever is later

## Current State

- release-candidate gate evidence exists for the current published release line
- GitHub release `v1.0.13a3` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`
- preflight provider health captured at `2026-04-12T23:12:49.569692Z` recorded OpenAI, Anthropic, and Ollama as healthy before traffic
- the first five eligible workflows were externally validated and accepted
- the sixth eligible workflow `run_06_ollama` reached `completed` internally but failed external artifact validation because the generated code omitted `main()`
- the canary was aborted and expansion frozen at 6 eligible workflows, far short of the minimum 7-day / 100-workflow window
- live checkpoint exports from `snapshot()` and `internal_runtime_telemetry()` were captured for the first accepted workflow and the aborting incident checkpoint

## Evidence References

- Phase 16 operations guide: `../canary-operations.md`
- repository evidence-root rules: `../README.md`
- current candidate parity and checkpoint record: `environment-parity.md`, `provider-health.json`, `workflow-summary.json`, `internal-runtime-telemetry.json`
- retained canary validation artifacts: `validation-artifacts/preflight-provider-health-2026-04-12T23-12-49Z.json`, `validation-artifacts/checkpoint-through-run-06-2026-04-12T23-16-16Z.json`
- retained release evidence: Phase 15 canonical matrix `full_matrix_validation_2026_04_12_v7`, GitHub Actions runs `#456` and `#18`, and GitHub release `v1.0.13a3`