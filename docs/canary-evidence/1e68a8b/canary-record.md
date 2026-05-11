# Canary Record - 1e68a8b

Status: active; `3/3` accepted, `0` incidents, `0` rollback actions

This record opens the candidate evidence bundle for released commit `1e68a8bc8e6371b6b425e1ac9ce04e3677141628` and tag `v1.0.13b2`.

The Phase 16 replacement beta canary bundle was opened on `2026-05-11T11:02:46Z` after the published prerelease closed cleanly.

## Candidate Identity

- candidate commit SHA: `1e68a8bc8e6371b6b425e1ac9ce04e3677141628`
- candidate commit subject: `chore: prepare v1.0.13b2 release candidate`
- branch: `main`
- release tag: `v1.0.13b2`
- package version: `1.0.13b2`

## Current Owner Binding

| Role | Current named owner | Contact path |
| --- | --- | --- |
| Release owner | Alexandre Andrade | `alex@kycortex.com` |
| Canary operator | Alexandre Andrade | `alex@kycortex.com` |
| Support responder | Alexandre Andrade | `alex@kycortex.com` |
| Security responder | Alexandre Andrade | `alex@kycortex.com` |

Role overlap is explicitly accepted for this maintainer-operated canary.

## Rollback Target

- rollback target SHA: `89d6e138bc5ff582c9fd2e8b31ec2e2b954c2bbc`
- rollback target role: latest canary-qualified published baseline (`v1.0.13a12`)
- rollback readiness: published release workflow and attached assets remain available for `v1.0.13a12`

## Canary Scope

- deployment class: single-maintainer controlled beta canary
- environment identifier: maintainer host pre-production runtime parity
- eligible workflow classes: `release-user-smoke`
- canary start time: `2026-05-11T11:02:46Z`
- minimum evidence window: at least 7 consecutive days or 100 eligible workflows, whichever is later

## Current State

- release-candidate gate evidence is available for `v1.0.13b2`
- GitHub prerelease publication closed with wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`
- canary traffic admitted: `2026-05-11T11:06:41Z` — first-accepted checkpoint reached
- smoke batch `canary_1e68a8b_smoke01`: `3/3` workflows accepted with rotated scenario assignment (anthropic=`baseline`, openai=`tight_margin`, ollama=`many_expenses`), `0` repair cycles, artifact_validation=passed
- provider health after first checkpoint: anthropic `1/1` accepted, openai `1/1` accepted, ollama `1/1` accepted
- incidents: `0`
- rollbacks: `0`
- next checkpoint: `10-workflows`

## Evidence References

- policy and operations: `../canary-operations.md`, `../go-live-policy.md`
- candidate parity material: `environment-parity.md`
- provider health snapshot: `provider-health.json`
- workflow rollup: `workflow-summary.json`
- telemetry checkpoint: `internal-runtime-telemetry.json`
- canary logs: `incident-log.md`, `rollback-log.md`, `completion-review.md`
- retained validation root for this candidate: `validation-artifacts/`
- first-accepted checkpoint: `validation-artifacts/checkpoint-first-accepted-2026-05-11T110641Z.json`