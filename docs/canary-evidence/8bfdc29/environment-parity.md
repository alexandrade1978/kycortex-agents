# Environment Parity - 8bfdc29

Status: live host pinned and checkpoint evidence recorded; canary aborted after code-validation incident on `run_04_openai`

This document records the concrete live canary environment values that were observed before traffic started and through the aborting checkpoint.

| Surface | Intended setting | Current evidence | Status |
| --- | --- | --- | --- |
| Candidate identity | Commit `8bfdc29516df09ccce0488352f5246b1d9be1091`, tag `v1.0.13a4`, package `1.0.13a4` | GitHub verified commit and tag, GitHub Actions CI run `#460` green, GitHub Actions Release run `#19` green, published release assets verified | confirmed |
| Historical disqualified release | Commit `25633830213afd029418b2a856e097b2403edc4f`, tag `v1.0.13a3`, package `1.0.13a3` | Abort evidence in `../2563383/` proves this published release cannot be reused for rollback or resumed canary continuation | recorded historical only |
| Rollback target | Commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`, tag `v1.0.13a2`, package `1.0.13a2` | Previous known-good published release plus controlled rollback re-smoke evidence retained in `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json` | confirmed baseline / not activated |
| Canary host | Native maintainer-operated Linux host `alex-kycortex` | Preflight provider health captured on `Linux-6.17.0-20-generic-x86_64-with-glibc2.39`, Python `3.12.3`, with the maintainer provider env file present before traffic | confirmed |
| Provider set | OpenAI `gpt-4o-mini`, Anthropic `claude-haiku-4-5-20251001`, and Ollama `qwen2.5-coder:7b` at `http://127.0.0.1:11434` | Preflight provider health was healthy for all three providers at `2026-04-13T00:56:52.840533Z`, refreshed expansion provider health was healthy for all three at `2026-04-13T01:28:52.992574Z`, and the first 4 controlled workflows hit the same provider/model set; OpenAI later triggered a code-validation incident on `run_04_openai` | confirmed; rollout aborted on candidate-quality evidence |
| Persistence backend | Same persisted `ProjectState` backend and artifact retention used by the live canary class | File-backed `ProjectState` JSON persisted under `/home/tupira/Dados/experiments/kycortex_agents/canary_8bfdc29_2026_04_13T00_56_30Z/eligible_workflows/.../project_state.json` | confirmed |
| Sandbox policy | Same sandbox restrictions as the published `v1.0.13a4` artifact | The first checkpoint used the released candidate defaults with no environment-specific sandbox override recorded in the workflow config; generated code import validation remained sandboxed with network and subprocess access disabled | provisional but consistent |
| Release settings | Same retry, repair, and release settings as the published `v1.0.13a4` artifact | Controlled `release-user-smoke` runs used `workflow_failure_policy=continue`, `workflow_max_repair_cycles=1`, `temperature=0.0`, `max_tokens=700`, `timeout_seconds=180.0`, and Ollama `num_ctx=16384` | confirmed |
| Telemetry access | Operator can export both `snapshot()` and `internal_runtime_telemetry()` from the same persisted state | The first accepted OpenAI checkpoint and the aborting OpenAI code-validation incident checkpoint were both exported from repository-owned state and matched against the retained generated artifacts | confirmed |

## Admission Outcome

The canary window opened after the live host, provider set, persistence path, and operator telemetry path were all pinned into repository-owned evidence.

Expansion reached one clean accepted workflow on each supported provider, but `run_04_openai` later failed external artifact validation because the generated artifact imported missing third-party dependency `click`. That left bounded termination intact while dropping accepted workflow rate to `75.0%`, which triggered rollback policy and froze further canary admission.

No live cutover back to `v1.0.13a2` was required because traffic never advanced beyond the controlled subset.