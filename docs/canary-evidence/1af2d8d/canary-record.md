# Canary Record - 1af2d8d

Status: live window open; preflight admission evidence captured, canary traffic not yet admitted

This record opens the candidate evidence bundle for released commit `1af2d8df1498ec2d98a09f9a7d2fa3767225532f` and tag `v1.0.13a11`.

The Phase 16 canary window was opened on `2026-05-04T05:11:04Z` after a clean canonical 5x3 preflight validation run.

## Candidate Identity

- candidate commit SHA: `1af2d8df1498ec2d98a09f9a7d2fa3767225532f`
- candidate commit subject: `Release v1.0.13a11`
- branch: `main`
- release tag: `v1.0.13a11`
- package version: `1.0.13a11`

## Current Owner Binding

| Role | Current named owner | Contact path |
| --- | --- | --- |
| Release owner | Alexandre Andrade | `alex@kycortex.com` |
| Canary operator | Alexandre Andrade | `alex@kycortex.com` |
| Support responder | Alexandre Andrade | `alex@kycortex.com` |
| Security responder | Alexandre Andrade | `alex@kycortex.com` |

Role overlap is explicitly accepted for this maintainer-operated canary.

## Rollback Target

- rollback target SHA: `8215089f1dcdef354e7711b9d90327a709b51129`
- rollback target role: current post-release mainline baseline
- rollback readiness: repository baseline validation remains green (`pytest`, `ruff`, `mypy`, release checks)

## Canary Scope

- deployment class: single-maintainer controlled canary
- environment identifier: maintainer host pre-production runtime parity
- eligible workflow classes: `release-user-smoke`
- canary start time: `2026-05-04T05:11:04Z`
- minimum evidence window: at least 7 consecutive days or 100 eligible workflows, whichever is later

## Current State

- release-candidate gate evidence is available for `v1.0.13a11`
- canonical preflight run completed cleanly at `output/real_world_complex_matrix_2026_05_04_v1013a11_final_5x3`
- preflight matrix result: 15/15 accepted with `terminal_outcome=completed` in all cells
- canary traffic admission has not started yet; this record captures the canary-open baseline only

## Evidence References

- policy and operations: `../canary-operations.md`, `../go-live-policy.md`
- candidate parity material: `environment-parity.md`
- preflight provider snapshot: `provider-health.json`
- preflight workflow rollup: `workflow-summary.json`
- telemetry checkpoint: `internal-runtime-telemetry.json`
- canary logs: `incident-log.md`, `rollback-log.md`, `completion-review.md`
- retained validation root for this candidate: `validation-artifacts/`
