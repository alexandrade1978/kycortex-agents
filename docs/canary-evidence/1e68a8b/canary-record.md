# Canary Record - 1e68a8b

Status: active; `106/107` accepted, `1` incident, `0` rollback actions

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
- smoke batch `canary_1e68a8b_smoke01`: `3/3` workflows accepted with rotated scenario assignment (anthropic=`baseline`, openai=`tight_margin`, ollama=`many_expenses`), `0` repair cycles, persisted artifact validation passed
- smoke batch `canary_1e68a8b_smoke02`: `3/3` workflows accepted with rotated scenario assignment (anthropic=`tight_margin`, openai=`many_expenses`, ollama=`baseline`), `0` repair cycles, persisted artifact validation passed
- smoke batch `canary_1e68a8b_smoke03`: `3/3` workflows accepted with rotated scenario assignment (anthropic=`many_expenses`, openai=`baseline`, ollama=`tight_margin`), `0` repair cycles, persisted artifact validation passed
- smoke batch `canary_1e68a8b_smoke04`: `1/1` workflows accepted (`anthropic=baseline`), `0` repair cycles, persisted artifact validation passed
- 10-workflows checkpoint reached at `2026-05-11T11:26:33Z`: cumulative `10/10` accepted, `0` incidents, `0` rollbacks
- smoke batches `canary_1e68a8b_smoke05` through `canary_1e68a8b_smoke09`: `15/15` workflows accepted across all three providers with the repeated rotated scenario cycle (baseline, tight_margin, many_expenses), `0` repair cycles, persisted artifact validation passed
- 25-workflows checkpoint reached at `2026-05-11T11:47:20Z`: cumulative `25/25` accepted, `0` incidents, `0` rollbacks
- provider health after 25-workflows checkpoint: anthropic `9/9` accepted, openai `8/8` accepted, ollama `8/8` accepted
- smoke batches `canary_1e68a8b_smoke10` through `canary_1e68a8b_smoke17`: `24/24` workflows accepted across all three providers with the repeated rotated scenario cycle (baseline, tight_margin, many_expenses), `acceptance_criteria_met=true` on every persisted workflow, task public-contract preflight and import validation passing on every code task, and `0` repair cycles
- smoke batch `canary_1e68a8b_smoke18`: `1/1` workflow accepted (`anthropic=many_expenses`), with `acceptance_criteria_met=true`, task public-contract preflight passed, import validation passed, and `0` repair cycles
- 50-workflows checkpoint reached at `2026-05-11T12:06:20Z`: cumulative `50/50` accepted, `0` incidents, `0` rollbacks
- provider health after 50-workflows checkpoint: anthropic `18/18` accepted, openai `16/16` accepted, ollama `16/16` accepted
- smoke batches `canary_1e68a8b_smoke19` through `canary_1e68a8b_smoke26`: `24/24` workflows accepted across all three providers with the repeated rotated scenario cycle (baseline, tight_margin, many_expenses), `acceptance_criteria_met=true` on every persisted workflow, task public-contract preflight and import validation passing on every code task, and `0` repair cycles
- smoke batches `canary_1e68a8b_smoke27` through `canary_1e68a8b_smoke34`: `24/24` workflows accepted across all three providers with the repeated rotated scenario cycle (baseline, tight_margin, many_expenses), `acceptance_criteria_met=true` on every persisted workflow, task public-contract preflight and import validation passing on every code task, and `0` repair cycles
- smoke batch `canary_1e68a8b_smoke35`: `2/2` workflows accepted (`anthropic=tight_margin`, `openai=many_expenses`), with `acceptance_criteria_met=true`, task public-contract preflight passed, import validation passed, and `0` repair cycles
- 100-workflows checkpoint reached at `2026-05-11T12:30:16Z`: cumulative `100/100` accepted, `0` incidents, `0` rollbacks
- provider health after 100-workflows checkpoint: anthropic `35/35` accepted, openai `33/33` accepted, ollama `32/32` accepted
- smoke batch `canary_1e68a8b_smoke36`: `2/3` workflows accepted with rotated scenario assignment (anthropic=`many_expenses`, openai=`baseline`, ollama=`tight_margin`); `openai=baseline` and `ollama=tight_margin` passed with persisted `acceptance_criteria_met=true`, task public-contract preflight passed, import validation passed, and `0` repair cycles, while `anthropic=many_expenses` failed in `arch` with retryable `ProviderTransientError` before code-task validation began
- smoke batch `canary_1e68a8b_smoke36_retry1`: `1/1` workflow accepted on a fresh root for the same provider/scenario pair (`anthropic=many_expenses`), with `acceptance_criteria_met=true`, task public-contract preflight passed, import validation passed, and `0` repair cycles
- daily-review day-1 reached at `2026-05-11T12:41:39Z`: cumulative `103/104` accepted, `1` incident, `0` rollbacks
- provider health after daily-review day-1: anthropic `36/37` accepted, openai `34/34` accepted, ollama `33/33` accepted
- smoke batch `canary_1e68a8b_smoke37`: `3/3` workflows accepted with rotated scenario assignment (anthropic=`baseline`, openai=`tight_margin`, ollama=`many_expenses`), with `acceptance_criteria_met=true`, task public-contract preflight passed, import validation passed, and `0` repair cycles on all three providers
- same-day daily-review follow-up recorded at `2026-05-11T12:58:41Z`: cumulative `106/107` accepted, `1` incident, `0` rollbacks
- provider health after the same-day follow-up: anthropic `37/38` accepted, openai `35/35` accepted, ollama `34/34` accepted
- the same `anthropic=baseline` provider/scenario pair that failed on held candidate `c17c749` passed cleanly on `1e68a8b`
- incidents: `1` (`provider_transient` on `anthropic=many_expenses` in `smoke36`, recovered on `smoke36_retry1`)
- rollbacks: `0`
- next checkpoint: `daily-review day-2`

## Evidence References

- policy and operations: `../canary-operations.md`, `../go-live-policy.md`
- candidate parity material: `environment-parity.md`
- provider health snapshot: `provider-health.json`
- workflow rollup: `workflow-summary.json`
- telemetry checkpoint: `internal-runtime-telemetry.json`
- canary logs: `incident-log.md`, `rollback-log.md`, `completion-review.md`
- retained validation root for this candidate: `validation-artifacts/`
- first-accepted checkpoint: `validation-artifacts/checkpoint-first-accepted-2026-05-11T110641Z.json`
- 10-workflows checkpoint: `validation-artifacts/checkpoint-10-workflows-2026-05-11T112633Z.json`
- 25-workflows checkpoint: `validation-artifacts/checkpoint-25-workflows-2026-05-11T114720Z.json`
- 50-workflows checkpoint: `validation-artifacts/checkpoint-50-workflows-2026-05-11T120620Z.json`
- 100-workflows checkpoint: `validation-artifacts/checkpoint-100-workflows-2026-05-11T123016Z.json`
- daily-review day-1: `validation-artifacts/daily-review-2026-05-11T124139Z.json`
- same-day daily-review follow-up: `validation-artifacts/daily-review-2026-05-11T125841Z.json`