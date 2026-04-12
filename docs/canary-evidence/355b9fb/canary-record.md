# Canary Record - 355b9fb

Status: pre-canary bootstrap

This record opens the candidate evidence bundle for commit `355b9fb55c7bf2b723927022e87e3edf9c28e63e`.

It does not claim that the canary window has started or closed.

## Candidate Identity

- candidate commit SHA: `355b9fb55c7bf2b723927022e87e3edf9c28e63e`
- candidate commit subject: `Bind canary operator roles`
- branch: `main`
- package version: `1.0.13a2`
- signature state: GitHub verified
- supporting GitHub Actions run: `#453` (`completed/success`)
- release-candidate baseline run: `#450` (`completed/success` on Phase 15 accepted commit `cd82118`)

## Current Owner Binding

| Role | Current named owner | Contact path |
| --- | --- | --- |
| Release owner | Alexandre Andrade | `alex@kycortex.com` |
| Canary operator | Alexandre Andrade | `alex@kycortex.com` |
| Support responder | Alexandre Andrade | `alex@kycortex.com` |
| Security responder | Alexandre Andrade | `alex@kycortex.com` |

## Rollback Target

- rollback target SHA: `cd8211879508713eec7880a161f82e41f6cf5a3a`
- rollback target role: last Phase 15 accepted candidate line with full empirical, local-validation, and GitHub CI closure
- rollback smoke status for the live canary environment: pending

## Canary Scope

- deployment class: single-maintainer pre-production canary
- environment identifier: pending explicit canary host record
- eligible workflow classes: pending explicit canary admission record
- canary start time: not started
- minimum evidence window: at least 7 consecutive days or 100 eligible workflows, whichever is later

## Current State

- release-candidate gate evidence exists for the current code line
- the canary window has not started yet
- live checkpoint exports from `snapshot()` and `internal_runtime_telemetry()` have not been collected yet
- this bundle is intentionally incomplete until the live window opens and closes

## Evidence References

- Phase 16 operations guide: `../canary-operations.md`
- repository evidence-root rules: `../README.md`
- current candidate parity and checkpoint placeholders: `environment-parity.md`, `provider-health.json`, `workflow-summary.json`, `internal-runtime-telemetry.json`
- retained release-candidate evidence: Phase 15 canonical matrix `full_matrix_validation_2026_04_12_v7`, local validation stack, GitHub Actions runs `#450` and `#453`