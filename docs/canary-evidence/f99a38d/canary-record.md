# Canary Record - f99a38d

Status: live window open; preflight and refreshed expansion health healthy through a clean 100-workflow checkpoint, first daily review, and day-3 daily review with 103 cumulative accepted workflows

This record opens the candidate evidence bundle for released commit `f99a38d1a08dceedcd0b520e302e3615f81d60f0` and tag `v1.0.13a6`.

The live Phase 16 window started on `2026-04-13T03:25:21Z` on the maintainer-operated host `alex-kycortex`.

The first accepted workflow completed on `2026-04-13T03:26:22.839835+00:00` after a controlled OpenAI `release-user-smoke` run finished `completed`, kept all 3 tasks at `done`, and passed external artifact validation.

The active canary then refreshed provider health at `2026-04-13T03:51:37.043973+00:00`, admitted the remaining controlled provider subset cleanly, reached a 10-eligible-workflow checkpoint at `2026-04-13T03:55:23.377066+00:00`, refreshed provider health again at `2026-04-13T04:03:29.889609+00:00`, reached a 25-eligible-workflow checkpoint at `2026-04-13T04:08:17.863018+00:00`, refreshed provider health a third time at `2026-04-13T04:15:41.775710+00:00`, reached a 50-eligible-workflow checkpoint at `2026-04-13T04:22:59.352947+00:00` with 50 accepted workflows, 0 incidents, and 0 rollback actions, recorded the first same-day daily review at `2026-04-13T04:30:01.447970+00:00`, refreshed provider health again at `2026-04-13T09:22:33.389958+00:00` and `2026-04-13T09:41:39.329840+00:00`, and reached a 100-eligible-workflow checkpoint at `2026-04-13T10:39:05.274887+00:00` with 100 accepted workflows, 0 incidents, and 0 rollback actions.

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
- refreshed expansion provider health captured at `2026-04-13T03:51:37.043973+00:00`, `2026-04-13T04:03:29.889609+00:00`, and `2026-04-13T04:15:41.775710+00:00` kept OpenAI, Anthropic, and Ollama healthy before broader admission
- the active window currently has 103 eligible workflows seen, 103 accepted workflows, 0 incidents, 0 rollback actions, and provider breakdown OpenAI 35, Anthropic 34, Ollama 34
- the first same-day daily review is recorded at `2026-04-13T04:30:01.447970+00:00` and confirmed the active window remains inside the current policy envelope
- the day-3 daily review is recorded at `2026-04-15T03:04:11.348007+00:00` with provider health refreshed at `2026-04-15T02:59:27.485280+00:00` and 3 new continuation smoke runs all completing cleanly
- the next required checkpoint is a daily review while the window remains open; the 100-workflow threshold is satisfied, but the 7-day minimum is still outstanding (target: `2026-04-20T03:25:21Z`)
- live checkpoint exports from `snapshot()` and `internal_runtime_telemetry()` have been captured for the first accepted workflow and the clean checkpoints through run 10, run 25, run 50, and run 100; the first same-day daily review still references the earlier run-50 evidence packet while the latest repository-owned checkpoint now extends through run 100

## Evidence References

- Phase 16 operations guide: `../canary-operations.md`
- repository evidence-root rules: `../README.md`
- current candidate parity and checkpoint record: `environment-parity.md`, `provider-health.json`, `workflow-summary.json`, `internal-runtime-telemetry.json`
- retained canary validation artifacts: `validation-artifacts/preflight-provider-health-2026-04-13T03-25-21Z.json`, `validation-artifacts/expansion-provider-health-2026-04-13T03-51-37Z.json`, `validation-artifacts/expansion-provider-health-2026-04-13T04-03-29Z.json`, `validation-artifacts/expansion-provider-health-2026-04-13T04-15-41Z.json`, `validation-artifacts/expansion-provider-health-2026-04-13T09-22-33Z.json`, `validation-artifacts/expansion-provider-health-2026-04-13T09-41-39Z.json`, `validation-artifacts/expansion-provider-health-2026-04-15T02-59-27Z.json`, `validation-artifacts/checkpoint-first-accepted-2026-04-13T03-26-22Z.json`, `validation-artifacts/checkpoint-through-run-10-2026-04-13T04-06-06Z.json`, `validation-artifacts/checkpoint-through-run-25-2026-04-13T04-08-17Z.json`, `validation-artifacts/checkpoint-through-run-50-2026-04-13T04-30-01Z.json`, `validation-artifacts/checkpoint-through-run-100-2026-04-13T10-40-58Z.json`, `validation-artifacts/checkpoint-daily-continuation-2026-04-15T03-04-11Z.json`, `validation-artifacts/daily-review-2026-04-13.md`, `validation-artifacts/daily-review-2026-04-15.md`
- retained rollback evidence for the approved rollback target: `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`
- retained release evidence: Phase 15 canonical matrix `full_matrix_validation_2026_04_12_v7`, local `python scripts/release_check.py`, tagged Release workflow `#21`, and GitHub release `v1.0.13a6`