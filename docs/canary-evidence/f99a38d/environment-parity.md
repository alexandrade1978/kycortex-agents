# Environment Parity - f99a38d

Status: live host pinned and the 10-workflow checkpoint recorded; canary window remains open

This document records the concrete live canary environment values that were observed before traffic started and through the clean 10-workflow checkpoint.

| Surface | Intended setting | Current evidence | Status |
| --- | --- | --- | --- |
| Candidate identity | Commit `f99a38d1a08dceedcd0b520e302e3615f81d60f0`, tag `v1.0.13a6`, package `1.0.13a6` | GitHub verified commit and signed tag, tagged Release workflow `#21` green, published release assets verified | confirmed |
| Historical published abort | Commit `c74e957ae76e9605d21b91ccc6d36bd1f25be16c`, tag `v1.0.13a5`, package `1.0.13a5` | Abort evidence in `../c74e957/` proves this published release cannot be resumed for the current live window | recorded historical only |
| Historical previous abort | Commit `8bfdc29516df09ccce0488352f5246b1d9be1091`, tag `v1.0.13a4`, package `1.0.13a4` | Abort evidence in `../8bfdc29/` proves this published release cannot be reused for rollback or resumed canary continuation | recorded historical only |
| Historical disqualified release | Commit `25633830213afd029418b2a856e097b2403edc4f`, tag `v1.0.13a3`, package `1.0.13a3` | Abort evidence in `../2563383/` proves this published release cannot be reused for rollback or resumed canary continuation | recorded historical only |
| Rollback target | Commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`, tag `v1.0.13a2`, package `1.0.13a2` | Previous known-good published release plus controlled rollback re-smoke evidence retained in `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json` | confirmed baseline / not activated |
| Canary host | Native maintainer-operated Linux host `alex-kycortex` | Preflight provider health captured on `Linux-6.17.0-20-generic-x86_64-with-glibc2.39`, Python `3.12.3`, with the maintainer provider env file present before traffic | confirmed |
| Provider set | OpenAI `gpt-4o-mini`, Anthropic `claude-haiku-4-5-20251001`, and Ollama `qwen2.5-coder:7b` at `http://127.0.0.1:11434` | Preflight provider health was healthy for all three providers at `2026-04-13T03:25:21Z`, refreshed expansion health stayed healthy at `2026-04-13T03:51:37.043973+00:00`, and the first 10 eligible workflows completed cleanly across all three providers | confirmed through run 10 |
| Persistence backend | Same persisted `ProjectState` backend and artifact retention used by the live canary class | File-backed `ProjectState` JSON persisted under `/home/tupira/Dados/experiments/kycortex_agents/canary_f99a38d_2026_04_13T03_25_21Z/eligible_workflows/.../project_state.json` | confirmed |
| Sandbox policy | Same sandbox restrictions as the published `v1.0.13a6` artifact | The first 10 accepted checkpoints used the released candidate defaults with no environment-specific sandbox override recorded in the workflow config; generated code import validation remained sandboxed with network and subprocess access disabled | confirmed through run 10 |
| Release settings | Same retry, repair, and release settings as the published `v1.0.13a6` artifact | Controlled `release-user-smoke` runs used `workflow_failure_policy=continue`, `workflow_max_repair_cycles=1`, `temperature=0.0`, `max_tokens=700`, `timeout_seconds=180.0`, and Ollama `num_ctx=16384` | confirmed |
| Telemetry access | Operator can export both `snapshot()` and `internal_runtime_telemetry()` from the same persisted state | The first accepted OpenAI checkpoint and the clean checkpoint through run 10 were exported from repository-owned state and validated against the generated artifacts | confirmed |

## Admission Outcome

The canary window opened after the live host, provider set, persistence path, and operator telemetry path were all pinned into repository-owned evidence.

The canary expanded from the smallest practical subset only after refreshed provider health remained healthy. The resulting 10-eligible-workflow checkpoint stayed clean across OpenAI, Anthropic, and Ollama.