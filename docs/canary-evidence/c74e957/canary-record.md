# Canary Record - c74e957

Status: aborted after code-validation incident on `release_user_smoke_ollama`

This record opens the candidate evidence bundle for released commit `c74e957ae76e9605d21b91ccc6d36bd1f25be16c` and tag `v1.0.13a5`.

The live Phase 16 window started on `2026-04-13T02:34:33Z` on the maintainer-operated host `alex-kycortex`.

The window was aborted on `2026-04-13T02:49:28.144777+00:00` after `release_user_smoke_ollama` generated a Python artifact without `main()`, causing external artifact validation to fail with `Generated code did not expose main().`. The incident preserved bounded termination, but it dropped accepted workflow rate to `66.7%`, missed the canary SLO, and triggered rollback policy.

## Candidate Identity

- candidate commit SHA: `c74e957ae76e9605d21b91ccc6d36bd1f25be16c`
- candidate commit subject: `Prepare v1.0.13a5 release candidate`
- branch: `main`
- release tag: `v1.0.13a5`
- package version: `1.0.13a5`
- signature state: GitHub verified commit and signed tag published
- supporting GitHub Actions release workflow: `#20` (`completed/success`)
- release-candidate baseline run: `python scripts/release_check.py` completed successfully on the tagged candidate line

## Current Owner Binding

| Role | Current named owner | Contact path |
| --- | --- | --- |
| Release owner | Alexandre Andrade | `alex@kycortex.com` |
| Canary operator | Alexandre Andrade | `alex@kycortex.com` |
| Support responder | Alexandre Andrade | `alex@kycortex.com` |
| Security responder | Alexandre Andrade | `alex@kycortex.com` |

## Rollback Target

- rollback target SHA: `b2dc9931d12c5d31651a97bba8c99e767b582ff8`
- rollback target tag: `v1.0.13a2`
- rollback target role: last published known-good alpha line with retained rollback re-smoke evidence
- rollback smoke status for the live canary environment: previously re-smoke-validated on the maintainer host and still retained under `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`

## Canary Scope

- deployment class: single-maintainer pre-production canary
- environment identifier: `/home/tupira/Dados/experiments/kycortex_agents/canary_c74e957_2026_04_13T02_34_33Z/`
- eligible workflow classes: `release-user-smoke`
- canary start time: `2026-04-13T02:34:33Z`
- minimum evidence window: at least 7 consecutive days or 100 eligible workflows, whichever is later

## Current State

- release-candidate gate evidence exists for the current published release line, and GitHub release `v1.0.13a5` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`
- historical abort evidence for the published `v1.0.13a4` line is retained under `../8bfdc29/`
- historical abort evidence for the disqualified `v1.0.13a3` line is retained under `../2563383/`
- preflight provider health captured at `2026-04-13T02:34:45.948542+00:00` recorded OpenAI, Anthropic, and Ollama as healthy before traffic
- expansion provider health refreshed at `2026-04-13T02:47:53.463682+00:00` recorded OpenAI, Anthropic, and Ollama as healthy before broader admission
- the first 2 controlled workflows `release_user_smoke_openai` and `release_user_smoke_anthropic` were externally validated and accepted by `2026-04-13T02:48:28.191709+00:00`
- the third controlled workflow `release_user_smoke_ollama` finished `failed` with `failure_category=code_validation` after external artifact validation rejected `artifacts/code_implementation.py` because the generated module did not expose `main()`
- the canary was aborted and expansion frozen at 3 eligible workflows because accepted workflow rate fell to `66.7%`, missed the `>=95.0%` canary SLO, and triggered rollback policy
- no broader customer-facing traffic remained to drain, so the rollback decision froze further admission without requiring a live cutover away from the controlled subset
- live checkpoint exports from `snapshot()` and `internal_runtime_telemetry()` have been captured for the first accepted workflow and the aborting code-validation incident checkpoint

## Evidence References

- Phase 16 operations guide: `../canary-operations.md`
- repository evidence-root rules: `../README.md`
- current candidate parity and checkpoint record: `environment-parity.md`, `provider-health.json`, `workflow-summary.json`, `internal-runtime-telemetry.json`
- retained canary validation artifacts: `validation-artifacts/preflight-provider-health-2026-04-13T02-34-45Z.json`, `validation-artifacts/checkpoint-first-accepted-2026-04-13T02-35-04Z.json`, `validation-artifacts/expansion-provider-health-2026-04-13T02-47-53Z.json`, `validation-artifacts/checkpoint-through-run-03-2026-04-13T02-49-28Z.json`
- retained rollback evidence for the approved rollback target: `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`
- retained release evidence: Phase 15 canonical matrix `full_matrix_validation_2026_04_12_v7`, local `python scripts/release_check.py`, tagged Release workflow `#20`, and GitHub release `v1.0.13a5`