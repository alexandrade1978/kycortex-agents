# Canary Record - 2563383

Status: pre-canary bootstrap

This record opens the candidate evidence bundle for released commit `25633830213afd029418b2a856e097b2403edc4f` and tag `v1.0.13a3`.

It does not claim that the canary window has started or closed.

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
- rollback smoke status for the live canary environment: pending

## Canary Scope

- deployment class: single-maintainer pre-production canary
- environment identifier: pending explicit canary host record
- eligible workflow classes: pending explicit canary admission record
- canary start time: not started
- minimum evidence window: at least 7 consecutive days or 100 eligible workflows, whichever is later

## Current State

- release-candidate gate evidence exists for the current published release line
- GitHub release `v1.0.13a3` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`
- the canary window has not started yet
- live checkpoint exports from `snapshot()` and `internal_runtime_telemetry()` have not been collected yet
- this bundle is intentionally incomplete until the live window opens and closes

## Evidence References

- Phase 16 operations guide: `../canary-operations.md`
- repository evidence-root rules: `../README.md`
- current candidate parity and checkpoint placeholders: `environment-parity.md`, `provider-health.json`, `workflow-summary.json`, `internal-runtime-telemetry.json`
- retained release evidence: Phase 15 canonical matrix `full_matrix_validation_2026_04_12_v7`, GitHub Actions runs `#456` and `#18`, and GitHub release `v1.0.13a3`