# Canary Record - f99a38d

Status: live window open; preflight and refreshed expansion health healthy through a clean 25-workflow checkpoint

This record opens the candidate evidence bundle for released commit `f99a38d1a08dceedcd0b520e302e3615f81d60f0` and tag `v1.0.13a6`.

The live Phase 16 window started on `2026-04-13T03:25:21Z` on the maintainer-operated host `alex-kycortex`.

The first accepted workflow completed on `2026-04-13T03:26:22.839835+00:00` after a controlled OpenAI `release-user-smoke` run finished `completed`, kept all 3 tasks at `done`, and passed external artifact validation.

The active canary then refreshed provider health at `2026-04-13T03:51:37.043973+00:00`, admitted the remaining controlled provider subset cleanly, reached a 10-eligible-workflow checkpoint at `2026-04-13T03:55:23.377066+00:00`, refreshed provider health again at `2026-04-13T04:03:29.889609+00:00`, and reached a 25-eligible-workflow checkpoint at `2026-04-13T04:08:17.863018+00:00` with 25 accepted workflows, 0 incidents, and 0 rollback actions.

## Candidate Identity

- candidate commit SHA: `f99a38d1a08dceedcd0b520e302e3615f81d60f0`
- candidate commit subject: `Prepare v1.0.13a6 release candidate`
- branch: `main`
- release tag: `v1.0.13a6`
- package version: `1.0.13a6`
- signature state: GitHub verified commit and signed tag published
- supporting GitHub Actions release workflow: `#21` (`completed/success`)
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
- environment identifier: `/home/tupira/Dados/experiments/kycortex_agents/canary_f99a38d_2026_04_13T03_25_21Z/`
- eligible workflow classes: `release-user-smoke`
- canary start time: `2026-04-13T03:25:21Z`
- minimum evidence window: at least 7 consecutive days or 100 eligible workflows, whichever is later

## Current State

- release-candidate gate evidence exists for the current published release line, and GitHub release `v1.0.13a6` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`
- historical abort evidence for the published `v1.0.13a5` line is retained under `../c74e957/`
- historical abort evidence for the published `v1.0.13a4` line is retained under `../8bfdc29/`
- historical abort evidence for the disqualified `v1.0.13a3` line is retained under `../2563383/`
- preflight provider health captured at `2026-04-13T03:25:21Z` recorded OpenAI, Anthropic, and Ollama as healthy before traffic
- the first controlled workflow `release_user_smoke_openai` was externally validated and accepted at `2026-04-13T03:26:22.839835+00:00`
- refreshed expansion provider health captured at `2026-04-13T03:51:37.043973+00:00` and `2026-04-13T04:03:29.889609+00:00` kept OpenAI, Anthropic, and Ollama healthy before broader admission
- the active window currently has 25 eligible workflows seen, 25 accepted workflows, 0 incidents, and 0 rollback actions
- the next required checkpoint is 50 eligible workflows or daily review, whichever comes first
- live checkpoint exports from `snapshot()` and `internal_runtime_telemetry()` have been captured for the first accepted workflow, the clean checkpoint through run 10, and the clean checkpoint through run 25

## Evidence References

- Phase 16 operations guide: `../canary-operations.md`
- repository evidence-root rules: `../README.md`
- current candidate parity and checkpoint record: `environment-parity.md`, `provider-health.json`, `workflow-summary.json`, `internal-runtime-telemetry.json`
- retained canary validation artifacts: `validation-artifacts/preflight-provider-health-2026-04-13T03-25-21Z.json`, `validation-artifacts/expansion-provider-health-2026-04-13T03-51-37Z.json`, `validation-artifacts/expansion-provider-health-2026-04-13T04-03-29Z.json`, `validation-artifacts/checkpoint-first-accepted-2026-04-13T03-26-22Z.json`, `validation-artifacts/checkpoint-through-run-10-2026-04-13T04-06-06Z.json`, `validation-artifacts/checkpoint-through-run-25-2026-04-13T04-08-17Z.json`
- retained rollback evidence for the approved rollback target: `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`
- retained release evidence: Phase 15 canonical matrix `full_matrix_validation_2026_04_12_v7`, local `python scripts/release_check.py`, tagged Release workflow `#21`, and GitHub release `v1.0.13a6`