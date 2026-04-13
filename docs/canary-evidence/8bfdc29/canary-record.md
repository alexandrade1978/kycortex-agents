# Canary Record - 8bfdc29

Status: live window open; preflight healthy and first checkpoint accepted

This record opens the candidate evidence bundle for released commit `8bfdc29516df09ccce0488352f5246b1d9be1091` and tag `v1.0.13a4`.

The live Phase 16 window started on `2026-04-13T00:56:30Z` on the maintainer-operated host `alex-kycortex`.

The first accepted workflow completed on `2026-04-13T00:57:23.746148+00:00` after a controlled OpenAI `release-user-smoke` run finished `completed`, kept all 3 tasks at `done`, and passed external artifact validation.

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
- the first controlled workflow `release_user_smoke_openai` was externally validated and accepted at `2026-04-13T00:57:23.746148+00:00`
- the active window currently has 1 eligible workflow seen, 1 accepted workflow, 0 incidents, and 0 rollback actions
- the next required checkpoint is 10 eligible workflows or the first incident, whichever comes first
- live checkpoint exports from `snapshot()` and `internal_runtime_telemetry()` have been captured for the first accepted workflow

## Evidence References

- Phase 16 operations guide: `../canary-operations.md`
- repository evidence-root rules: `../README.md`
- current candidate parity and checkpoint record: `environment-parity.md`, `provider-health.json`, `workflow-summary.json`, `internal-runtime-telemetry.json`
- retained canary validation artifacts: `validation-artifacts/preflight-provider-health-2026-04-13T00-56-52Z.json`, `validation-artifacts/checkpoint-first-accepted-2026-04-13T00-57-23Z.json`
- retained rollback evidence for the approved rollback target: `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`
- retained release evidence: Phase 15 canonical matrix `full_matrix_validation_2026_04_12_v7`, GitHub Actions run `#460`, GitHub Actions Release run `#19`, and GitHub release `v1.0.13a4`