# Go-Live Policy

This document defines the repository-owned production-readiness policy for KYCortex Agents.

Use it together with `RELEASE.md`.

A tagged package release publishes a versioned artifact. It does not, by itself, declare the framework ready for production customer traffic.

## Current Status

- The public package line remains Alpha.
- `1.0.13a6` is the current released alpha baseline and the active published Phase 16 canary candidate, with the live evidence bundle tracked at `docs/canary-evidence/f99a38d/` after healthy three-provider preflight, repeated healthy expansion refreshes, and a clean 25-eligible-workflow checkpoint.
- `1.0.13a5` remains the previous historical published line below the current baseline, and its canary evidence remains the abort record at `docs/canary-evidence/c74e957/` after `release_user_smoke_ollama` triggered a code-validation incident.
- `1.0.13a4` remains the older historical published line below that baseline, and its canary evidence remains the abort record at `docs/canary-evidence/8bfdc29/`.
- There is currently an active Phase 16 canary candidate on a published tag.
- Production go-live is not declared until the gates in this document are satisfied and the decision is recorded in repository release materials.

## Scope

This policy applies to repository-owned workflow classes that rely on the orchestrator, generated artifacts, repair loops, persistence, sandboxed validation, and provider-backed execution.

The policy anchors three product rules:

- A workflow is successful only when its declared acceptance criteria pass end to end.
- Partial artifacts are auditable evidence, not successful outcomes.
- Safe failure is allowed; false success is not.

## Service Level Indicators

The following indicators are the production decision inputs for supported workflow classes:

- Accepted workflow rate: the share of eligible workflows that finish with their acceptance criteria met.
- False-success rate: the share of workflows reported as successful even though acceptance criteria were not satisfied.
- Bounded termination rate: the share of workflows that reach a controlled terminal or operator-visible state within configured workflow budgets.
- Autonomous recovery rate: the share of retryable or repairable incidents that converge without manual state editing.
- Resume integrity rate: the share of interrupted workflows that resume without losing the failing artifact, validation evidence, repair lineage, or persisted task history required for recovery.

These indicators must be derived from repository-owned state, execution events, validation artifacts, and operator-facing telemetry rather than from ad hoc log inspection.

## Service Level Objectives

| Objective | Target | Measurement Window | Hard Interpretation |
| --- | --- | --- | --- |
| Accepted workflow rate | `>= 95.0%` | Rolling 28 days per supported workflow class | Measures whether supported workflows actually converge to accepted outcomes in real execution. |
| False-success rate | `0.00%` | Rolling 28 days, and per-release candidate | Any workflow reported as successful without passing acceptance criteria is a stop-ship incident. |
| Bounded termination rate | `>= 99.5%` | Rolling 28 days | Workflows must end in a controlled state such as `completed`, `failed`, `paused`, or `cancelled` rather than hanging or silently exceeding budgets. |
| Autonomous recovery rate | `>= 90.0%` of retryable or repairable incidents | Rolling 28 days | Retryable provider failures and supported artifact defects should usually recover without operator edits. |
| Resume integrity rate | `>= 99.9%` | Rolling 28 days | Persisted resume must preserve the evidence needed for safe recovery and audit. |

## Error Budget Policy

KYCortex does not use a single blended error budget. It uses a severity-based policy tied to the objectives above.

### Zero-Budget Incident Classes

The following classes have no permitted budget in any release, canary, or general-availability claim:

- False success
- Silent state corruption or unrecoverable persisted-state loss
- Sandbox escape that mutates or reads host resources outside the allowed execution boundary
- Secret leakage through public state, public logs, public artifacts, or public release evidence

Any single incident in a zero-budget class freezes go-live promotion until the repository has:

- an identified root cause
- a merged fix
- regression coverage or equivalent deterministic validation
- a documented rollback or containment decision if the incident affected a staged environment

### Rolling Error Budgets

The following rolling budgets apply to supported workflow classes:

- Accepted workflow budget: up to `5.0%` non-accepted outcomes in the rolling 28-day window
- Bounded termination budget: up to `0.5%` workflows exceeding configured workflow budgets or requiring forced operator intervention to stop
- Autonomous recovery budget: up to `10.0%` retryable or repairable incidents requiring manual intervention
- Resume integrity budget: up to `0.1%` interrupted workflows losing required recovery evidence or failing clean resume

### Burn Rules

- Consuming more than `50%` of any non-zero budget in the first half of the measurement window blocks promotion to a broader rollout stage.
- Consuming `100%` of any non-zero budget blocks new production expansion until the burn rate returns to a compliant range and the recovery plan is documented.
- Consuming any zero-budget incident class immediately blocks go-live and wider rollout claims.

## Go-Live Gates

### Release-Candidate Gate

The repository may call a build a release candidate for go-live review only when all of the following are true:

- `python scripts/release_check.py` passes on the candidate commit.
- The package, release metadata, artifact manifest, promotion summary, and published-asset verification path are green.
- There are no open severity-1 defects in false-success, persistence corruption, sandbox escape, or secret-redaction boundaries.
- The retained provider-matrix baseline and the retained release-user smoke remain valid for the target release line.
- Real-world validation evidence is current enough to support the claim being made: either a fresh broader confirmation run exists, or the maintained recovery baseline plus the latest repaired smoke subset still provide sufficient counter-regression evidence with no newer contradictory result.
- Repository docs, release materials, and examples describe the same public runtime contract.

### Canary Gate

The repository may call a build canary-ready only when the release-candidate gate is satisfied and all of the following are true:

- The candidate meets every SLO target over a pre-production or controlled canary window of at least `7` consecutive days or `100` eligible workflows, whichever is later.
- No zero-budget incident class has occurred during that window.
- Phase 16 operator runbooks, rollback steps, support escalation rules, and incident templates are present and reviewed.
- The canary environment exposes the same provider, persistence, sandbox, and release settings that will be used for the intended deployment class.

### General-Availability Gate

The repository may call a build generally available only when the canary gate is satisfied and all of the following are true:

- Phase 17 production qualification is complete and explicitly signed off.
- The current measurement window remains inside every error budget.
- No unresolved stop-ship incident exists in the zero-budget classes.
- The production support model, rollback drill results, and release-ownership path are documented in repository-controlled operations material.

## Release Versus Go-Live

The repository intentionally separates package release readiness from production go-live:

- `RELEASE.md` defines how to validate, tag, and publish versioned package artifacts.
- This document defines whether the framework is ready to carry real customer traffic under a production claim.
- Alpha or maintenance package releases may continue before general availability, but they must not be described as production-ready unless the go-live gates above are satisfied.

## Recording The Decision

Any future production go-live claim must be reflected in repository-owned release materials.

At minimum, that decision must update:

- `RELEASE_STATUS.md`
- `CHANGELOG.md`
- `README.md`
- any release note or promotion summary that describes the deployment claim

Until that happens, the correct public posture is: package-ready alpha line, not production go-live.