# Environment Parity - 355b9fb

Status: preflight drafted, canary admission blocked until the final live environment values are recorded

This document records what is already known for the current single-maintainer canary class and what still must be pinned before traffic starts.

| Surface | Intended setting | Current evidence | Status |
| --- | --- | --- | --- |
| Candidate identity | Commit `355b9fb55c7bf2b723927022e87e3edf9c28e63e`, package `1.0.13a2` | GitHub verified commit plus GitHub Actions run `#453` green | confirmed |
| Rollback target | Commit `cd8211879508713eec7880a161f82e41f6cf5a3a` | Phase 15 accepted line plus GitHub Actions run `#450` green | confirmed |
| Provider set | OpenAI, Anthropic, and Ollama with the maintainer-operated baseline model | Phase 15 canonical matrix `v7` cleared 5 of 5 per provider on the current runtime line | provisional |
| Persistence backend | Same persisted `ProjectState` backend and artifact retention used by the live canary class | Final live backend choice is not yet written into this record | pending |
| Sandbox policy | Same sandbox restrictions as the release-candidate line | Policy exists in the candidate line, but the live canary host record is still missing | pending |
| Release settings | Same retry, repair, and release settings as the line that cleared Phase 15 and CI | Candidate line is fixed, but the live host values are not yet recorded in one place | provisional |
| Telemetry access | Operator can export both `snapshot()` and `internal_runtime_telemetry()` from the same persisted state | Export procedure is documented in `../canary-operations.md`; live host path is still missing | pending |

## Admission Rule

Do not start the canary until every provisional or pending item above has been converted into a concrete environment record for the actual canary host.