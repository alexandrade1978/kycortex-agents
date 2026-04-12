# Environment Parity - 2563383

Status: preflight drafted, canary admission blocked until the final live environment values are recorded

This document records what is already known for the current single-maintainer canary class and what still must be pinned before traffic starts.

| Surface | Intended setting | Current evidence | Status |
| --- | --- | --- | --- |
| Candidate identity | Commit `25633830213afd029418b2a856e097b2403edc4f`, tag `v1.0.13a3`, package `1.0.13a3` | GitHub verified commit and tag, GitHub Actions CI run `#456` green, GitHub Actions Release run `#18` green | confirmed |
| Rollback target | Commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`, tag `v1.0.13a2`, package `1.0.13a2` | Previous published release plus GitHub Actions Release run `#17` green | confirmed |
| Provider set | OpenAI, Anthropic, and Ollama with the maintainer-operated baseline model | Phase 15 canonical matrix `v7` cleared 5 of 5 per provider on the release-candidate line and CI run `#456` stayed green on commit `2563383` | provisional |
| Persistence backend | Same persisted `ProjectState` backend and artifact retention used by the live canary class | Final live backend choice is not yet written into this record | pending |
| Sandbox policy | Same sandbox restrictions as published `v1.0.13a3` | Policy exists in the candidate line, but the live canary host record is still missing | pending |
| Release settings | Same retry, repair, and release settings as the published `v1.0.13a3` artifact | Published artifact exists, but the live host values are not yet recorded in one place | provisional |
| Telemetry access | Operator can export both `snapshot()` and `internal_runtime_telemetry()` from the same persisted state | Export procedure is documented in `../canary-operations.md`; live host path is still missing | pending |

## Admission Rule

Do not start the canary until every provisional or pending item above has been converted into a concrete environment record for the actual canary host.