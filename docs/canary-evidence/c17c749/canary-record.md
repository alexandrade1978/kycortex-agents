# Canary Record - c17c749

Status: open; `10/11` accepted, `1` incident, `0` rollbacks

This record opens the candidate evidence bundle for released commit `c17c7492d3aded8d0dfcf84087cd9a77712dad33` and tag `v1.0.13b1`.

The Phase 16 beta canary window was opened on `2026-05-11T09:53:39Z` after the published prerelease closed cleanly.

## Candidate Identity

- candidate commit SHA: `c17c7492d3aded8d0dfcf84087cd9a77712dad33`
- candidate commit subject: `release: prepare v1.0.13b1`
- branch: `main`
- release tag: `v1.0.13b1`
- package version: `1.0.13b1`

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
- rollback target role: latest published alpha baseline (`v1.0.13a12`)
- rollback readiness: published release workflow and attached assets remain available for `v1.0.13a12`

## Canary Scope

- deployment class: single-maintainer controlled beta canary
- environment identifier: maintainer host pre-production runtime parity
- eligible workflow classes: `release-user-smoke`
- canary start time: `2026-05-11T09:53:39Z`
- minimum evidence window: at least 7 consecutive days or 100 eligible workflows, whichever is later

## Current State

- release-candidate gate evidence is available for `v1.0.13b1`
- GitHub prerelease publication closed with wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`
- canary traffic admitted: `2026-05-11T09:54:03Z` — first-accepted checkpoint reached
- smoke batch `canary_c17c749_smoke01`: 3/3 workflows accepted with rotated scenario assignment (anthropic=`baseline`, openai=`tight_margin`, ollama=`many_expenses`), 0 repair cycles, artifact_validation=passed
- smoke batch `canary_c17c749_smoke02`: 3/3 workflows accepted with rotated scenario assignment (anthropic=`tight_margin`, openai=`many_expenses`, ollama=`baseline`), 0 repair cycles, artifact_validation=passed
- smoke batch `canary_c17c749_smoke03`: 3/3 workflows accepted with rotated scenario assignment (anthropic=`many_expenses`, openai=`baseline`, ollama=`tight_margin`), 0 repair cycles, artifact_validation=passed
- smoke batch `canary_c17c749_smoke04`: 0/1 workflows accepted (`anthropic=baseline`), `code_validation` incident recorded because the generated code artifact was not found
- 10-workflows checkpoint reached at `2026-05-11T10:02:33Z`: cumulative `9/10` accepted, `1` incident, `0` rollbacks
- smoke batch `canary_c17c749_smoke04_retry`: 1/1 workflows accepted on a fresh root for the same provider/scenario pair (`anthropic=baseline`), 0 repair cycles, artifact_validation=passed
- provider health after checkpoint and targeted replay: anthropic 4/5 accepted, openai 3/3 accepted, ollama 3/3 accepted
- incidents: 1 (`code_validation` on `anthropic=baseline` in `smoke04`)
- rollbacks: 0
- next checkpoint: incident review before further expansion

## Evidence References

- policy and operations: `../canary-operations.md`, `../go-live-policy.md`
- candidate parity material: `environment-parity.md`
- provider health snapshot: `provider-health.json`
- workflow rollup: `workflow-summary.json`
- telemetry checkpoint: `internal-runtime-telemetry.json`
- canary logs: `incident-log.md`, `rollback-log.md`, `completion-review.md`
- retained validation root for this candidate: `validation-artifacts/`
- first-accepted checkpoint: `validation-artifacts/checkpoint-first-accepted-2026-05-11T095403Z.json`
- 10-workflows checkpoint: `validation-artifacts/checkpoint-10-workflows-2026-05-11T100233Z.json`