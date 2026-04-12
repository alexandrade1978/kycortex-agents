# Canary Operations Guide

This document defines the repository-controlled Phase 16 operational material for canary readiness.

Use it together with `docs/go-live-policy.md` and `RELEASE.md`.

It does not declare the framework production-ready by itself. It defines the operator procedure and evidence expectations for a controlled canary window.

## Scope

This guide applies to candidate commits that already satisfy the release-candidate gate in `docs/go-live-policy.md` and are being evaluated for canary readiness.

The goals are:

- run a controlled canary on the same provider, persistence, sandbox, and release settings intended for the deployment class
- make rollback decisions deterministic and repository-owned
- keep incident handling consistent across canary attempts
- capture the minimum evidence required to close the Phase 16 canary gate

## Required Inputs

Before a canary starts, the operator must have all of the following:

- candidate commit SHA and package version
- previous known-good rollback target
- confirmed release-candidate gate evidence for the same candidate
- named release owner and named canary operator
- access to repository-owned telemetry, workflow state, validation artifacts, and provider-health evidence
- documented list of eligible workflow classes allowed into the canary window
- documented canary environment configuration proving parity for provider, persistence, sandbox, and release settings

## Roles

| Role | Primary responsibility |
| --- | --- |
| Release owner | Approves the candidate, owns promotion and rollback decisions, and signs the canary completion review. |
| Canary operator | Runs the canary procedure, watches SLOs and error budgets, and records incidents and checkpoints. |
| Support responder | Handles user-visible canary incidents, keeps the support timeline current, and confirms customer-impact status. |
| Security responder | Joins immediately for any sandbox, secret-leakage, or boundary incident. |

If one person holds multiple roles, that overlap must be recorded in the canary record before traffic starts.

## Preflight Checklist

Do not begin the canary until every item below is complete:

- the candidate commit is pinned and matches the artifact intended for the canary environment
- the previous known-good rollback target is available and smoke-validated
- provider credentials and endpoints are correct for the canary environment
- persistence backend, sandbox policy, retry settings, repair settings, and release settings match the intended deployment class
- operator access to `ProjectState.internal_runtime_telemetry()` or equivalent internal evidence has been validated
- the canary record has an owner, start time, environment description, and eligible workflow-class scope
- the support path and escalation contacts are current

## Canary Runbook

### 1. Open the canary record

Record the following before deployment:

- candidate SHA and version
- rollback target SHA and version
- canary environment identifier
- start time
- release owner
- canary operator
- eligible workflow classes

### 2. Deploy the candidate to the canary environment

- deploy the exact candidate artifact or commit selected for review
- confirm that the deployment uses the same provider, persistence, sandbox, and release settings intended for the deployment class
- record any environment-specific override that exists and justify it explicitly

If parity cannot be demonstrated, stop the canary and reopen only after the mismatch is removed or formally waived.

### 3. Run pre-canary health and smoke checks

Before any canary traffic is admitted:

- verify provider health for every enabled provider in the canary environment
- run the release-user smoke or equivalent targeted smoke for the supported workflow class
- verify that repository-owned telemetry and persisted-state evidence are visible for the candidate

Any failure in this step blocks canary admission and should be treated as a rollback-to-safe-state decision, not as a partial canary.

### 4. Start controlled canary traffic

- admit only eligible workflows defined in the canary record
- begin with the smallest practical controlled subset of eligible traffic
- expand only at explicit checkpoints after the current checkpoint remains within every SLO and error budget

Recommended checkpoints:

- first accepted workflow
- 10 eligible workflows
- 25 eligible workflows
- 50 eligible workflows
- 100 eligible workflows
- daily review until the minimum calendar window is satisfied

### 5. Monitor SLOs and error budgets during the window

At every checkpoint, review:

- accepted workflow rate
- false-success rate
- bounded termination rate
- autonomous recovery rate
- resume integrity rate
- zero-budget incident classes

If any checkpoint falls outside the policy in `docs/go-live-policy.md`, freeze expansion immediately and apply the rollback rules below.

### 6. Decide whether to expand, hold, or abort

- expand only when every SLO remains within target and no zero-budget incident occurred
- hold when the window is still valid but evidence is too thin for the next expansion step
- abort and roll back when any rollback trigger is met

### 7. Close the canary window

When the minimum evidence window is complete:

- produce the canary completion review
- record whether the candidate is canary-ready, held for further observation, or rolled back
- attach the evidence packet listed in the acceptance section below

## Rollback Triggers

Rollback is mandatory when any of the following occurs:

- any zero-budget incident class in `docs/go-live-policy.md`
- any SLO target missed during the canary window
- more than `50%` of any non-zero error budget consumed in the first half of the observation window
- environment parity drift between the canary environment and the intended deployment class
- required recovery evidence, validation artifacts, or internal telemetry becomes unavailable or untrustworthy
- retryable or repairable incidents require unsupported manual state editing to continue
- the release owner or canary operator cannot explain the current failure mode with repository-owned evidence

## Rollback Procedure

Execute the following in order:

1. freeze canary expansion immediately
2. stop routing new eligible workflows to the candidate
3. preserve the failing artifacts, workflow state, validation output, and operator notes needed for audit and recovery
4. switch traffic or deployment state back to the previous known-good rollback target
5. run the minimum health and smoke validation on the rollback target
6. record the rollback decision, timestamp, trigger, and owner in the incident log
7. notify support and release stakeholders of the rollback and current customer-impact assessment

Do not resume the same candidate until the root cause is documented and the decision to retry is explicitly recorded.

## Support Escalation Rules

| Severity | Trigger class | Immediate action | Required participants |
| --- | --- | --- | --- |
| `SEV0` | False success, sandbox escape, secret leakage, unrecoverable persisted-state loss, or any other zero-budget incident | Freeze expansion and roll back immediately | Release owner, canary operator, security responder, and support responder |
| `SEV1` | Canary rollback without a zero-budget incident, repeated accepted-workflow misses, bounded-termination miss, or resume-integrity concern | Freeze expansion, open an incident record, and prepare rollback unless evidence recovers quickly and policy remains intact | Release owner, canary operator, support responder |
| `SEV2` | Isolated retryable or repairable incident still inside policy budgets | Record the incident, monitor for repetition, and keep the checkpoint under review before any expansion | Canary operator, support responder |
| `SEV3` | Documentation, telemetry, or operational gap with no live canary impact | Record the issue for follow-up and correct it before the next canary attempt | Canary operator |

## Incident Templates

### Canary Incident Record

```text
Title:
Timestamp:
Candidate SHA / version:
Workflow class:
Severity:
Trigger:
Observed impact:
Evidence links:
Immediate action:
Rollback required: yes/no
Owner:
Next review time:
```

### Rollback Decision Record

```text
Candidate SHA / version:
Rollback target SHA / version:
Decision time:
Trigger:
Customer-impact summary:
Evidence reviewed:
Decision owner:
Validation performed on rollback target:
Follow-up actions:
```

### Canary Completion Review

```text
Candidate SHA / version:
Window start:
Window end:
Eligible workflow count:
Accepted workflow rate:
False-success rate:
Bounded termination rate:
Autonomous recovery rate:
Resume integrity rate:
Zero-budget incidents observed: yes/no
Environment parity confirmed: yes/no
Decision: canary-ready / hold / rollback
Reviewed by:
```

## Minimum Observation Window And Acceptance Evidence

The minimum canary window is the one defined in `docs/go-live-policy.md`:

- at least `7` consecutive days or `100` eligible workflows, whichever is later

The acceptance packet for that window must include all of the following:

- candidate SHA and version
- canary environment identifier and parity confirmation
- counts for eligible workflows and accepted workflows
- measured values for every SLO in the policy
- explicit statement that no zero-budget incident occurred during the window
- incident log, including empty log confirmation if no incidents occurred
- rollback decision log, including explicit confirmation that no rollback was needed if the window stayed healthy
- final canary completion review signed by the release owner and canary operator

## Review And Maintenance

- review this guide before each new canary claim
- keep it aligned with `docs/go-live-policy.md`, `RELEASE.md`, and repository-controlled release materials
- update the incident templates and escalation rules when the provider set, deployment class, or support model changes