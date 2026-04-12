# Canary Evidence Bundle

This directory is the repository-controlled root for Phase 16 canary evidence bundles.

Use it together with `../canary-operations.md` and `../go-live-policy.md`.

## Directory Rule

Create one directory per canary candidate commit:

```text
docs/canary-evidence/<candidate-sha>/
```

Example:

```text
docs/canary-evidence/be748fa/
```

## Minimum Contents

Each candidate directory should contain:

- `canary-record.md`
- `environment-parity.md`
- `provider-health.json`
- `workflow-summary.json`
- `internal-runtime-telemetry.json`
- `validation-artifacts/`
- `incident-log.md`
- `rollback-log.md`
- `completion-review.md`

## Source Rules

- use `ProjectState.snapshot()` for normalized public workflow summaries, execution events, artifact inventory, and decision inventory
- use `ProjectState.internal_runtime_telemetry()` for exact provider, latency, attempt, repair, and provider-health telemetry
- use repository-owned validation artifacts and structured runner outputs when broader summaries already exist
- do not rely on ad hoc terminal history or informal notes as the canonical evidence source

## Review Rule

If the evidence in this directory cannot explain the canary decision on its own, the canary record is incomplete and the candidate is not ready to close Phase 16.