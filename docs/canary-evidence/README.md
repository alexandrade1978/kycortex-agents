# Canary Evidence Bundle

This directory is the repository-controlled root for Phase 16 canary evidence bundles.

Use it together with `../canary-operations.md` and `../go-live-policy.md`.

It is repository-owned operational and historical material, not part of the primary public product documentation surface.

This README also acts as the compact operator index for the active bundle and retained historical bundles.

Candidate directories may be opened before traffic starts.

If the canary window has not started yet, every file in the candidate directory must say so explicitly. A pre-canary bundle is allowed, but it does not satisfy the Phase 16 gate until the live window evidence is present.

## Current Open Bundle

- Current active candidate: `1e68a8b` (`v1.0.13b2`)
- State: `daily-review day-2` recorded after a clean next-day review; cumulative `109/110` accepted workflows, `1` incident, `0` rollback actions
- Traffic admitted: `2026-05-11T11:06:41Z`
- Next checkpoint: `daily-review day-3`

## Current Held Bundle

- Current held candidate: `c17c749` (`v1.0.13b1`)
- State: policy hold; cumulative `10/11` accepted workflows, `1` incident, `0` rollback actions
- Traffic admitted: `2026-05-11T09:54:03Z`
- Hold reason: accepted-workflow rate remained below `>=95.0%` after the 10-workflows checkpoint and still sat at `10/11` after the retained replay; early budget burn exceeded the `5.0%` non-accepted budget
- Next checkpoint: root-cause review and explicit retry-or-replace decision before any new candidate traffic is admitted

## Directory Rule

Create one directory per canary candidate commit:

```text
docs/canary-evidence/<candidate-sha>/
```

Example:

```text
docs/canary-evidence/be748fa/
```

Historical bundles, abort bundles, and active candidate bundles may coexist under this root.

## Latest Retained Bundle

- Latest retained candidate: `1af2d8d` (`v1.0.13a11`)
- State: minimum window satisfied; historical bundle superseded by `v1.0.13a12` publication
- Current cumulative result: `121/121` accepted workflows, `0` incidents, `0` rollbacks
- Minimum window satisfied: `2026-05-11T05:11:04Z`

Published daily-review packets for the active cycle:

- `docs/canary-evidence/1af2d8d/validation-artifacts/daily-review-2026-05-04T130146Z.json`
- `docs/canary-evidence/1af2d8d/validation-artifacts/daily-review-2026-05-05T171308Z.json`
- `docs/canary-evidence/1af2d8d/validation-artifacts/daily-review-2026-05-06T215824Z.json`
- `docs/canary-evidence/1af2d8d/validation-artifacts/daily-review-2026-05-07T225734Z.json`
- `docs/canary-evidence/1af2d8d/validation-artifacts/daily-review-2026-05-09T024333Z.json`
- `docs/canary-evidence/1af2d8d/validation-artifacts/daily-review-2026-05-10T011452Z.json`
- `docs/canary-evidence/1af2d8d/validation-artifacts/daily-review-2026-05-11T070548Z.json`

## Retention View

Keep the following bundles under this root because they still carry operational or audit value:

| Candidate | State | Keep? | Reason |
| --- | --- | --- | --- |
| `1e68a8b` | active replacement beta canary under daily review after a recovered retryable provider incident and clean day-2 continuation | yes | Active replacement beta candidate for the held `v1.0.13b1` line; `daily-review day-1` retained one isolated `provider_transient` incident that recovered on targeted replay, the same-day follow-up `smoke37` refresh passed cleanly, and `daily-review day-2` `smoke38` then passed cleanly on all three providers while the `7`-day minimum window remained open. |
| `c17c749` | held beta canary after early accepted-workflow SLO miss | yes | Candidate-specific hold evidence for `v1.0.13b1`; keep until the retained incident is root-caused and the retry-or-replace decision is recorded. |
| `1af2d8d` | completed minimum-window canary, later superseded | yes | Retained historical evidence for the `v1.0.13a11` line after the repository moved forward with `v1.0.13a12` publication instead of promoting `v1.0.13a11`. |
| `f99a38d` | historical live window left open | yes | Retained evidence of an earlier canary that reached 100+ workflows and daily reviews; useful for lineage and prior operator decisions. |
| `c74e957` | aborted after code-validation incident | yes | Zero-budget incident evidence must remain reviewable. |
| `8bfdc29` | aborted after code-validation incident | yes | Retained abort evidence for failed candidate history. |
| `2563383` | aborted after false-success incident | yes | Retained false-success evidence and rollback smoke baseline. |

The following bundles have lower ongoing value because traffic never started:

| Candidate | State | Default action | Reason |
| --- | --- | --- | --- |
| `03d6403` | pre-canary evidence rebuild | retain unless archived deliberately | Useful as provenance for the repository-controlled rebuild of a lost late-phase evidence chain. |
| `355b9fb` | pre-canary bootstrap | retain unless archived deliberately | Documents role-binding/bootstrap history, but it is a candidate for later archival if root clutter becomes a real problem. |

Operational rule: do not delete historical bundles that are referenced by newer rollback, incident, or completion-review material. If clutter becomes a problem, move only pre-canary bundles to an explicit archival location after updating all references.

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