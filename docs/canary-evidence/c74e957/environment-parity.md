# Environment Parity - c74e957

Status: live host pinned; window aborted after an Ollama code-validation incident on the third controlled workflow

This document records the concrete live canary environment values that were observed before traffic started, during the expansion health refresh, and at the aborting checkpoint.

| Surface | Intended setting | Current evidence | Status |
| --- | --- | --- | --- |
| Candidate identity | Commit `c74e957ae76e9605d21b91ccc6d36bd1f25be16c`, tag `v1.0.13a5`, package `1.0.13a5` | GitHub verified commit and signed tag, tagged Release workflow `#20` green, published release assets verified | confirmed |
| Historical published abort | Commit `8bfdc29516df09ccce0488352f5246b1d9be1091`, tag `v1.0.13a4`, package `1.0.13a4` | Abort evidence in `../8bfdc29/` proves this published release cannot be resumed for the current live window | recorded historical only |
| Historical disqualified release | Commit `25633830213afd029418b2a856e097b2403edc4f`, tag `v1.0.13a3`, package `1.0.13a3` | Abort evidence in `../2563383/` proves this published release cannot be reused for rollback or resumed canary continuation | recorded historical only |
| Rollback target | Commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`, tag `v1.0.13a2`, package `1.0.13a2` | Previous known-good published release plus controlled rollback re-smoke evidence retained in `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json` | confirmed baseline / not activated |
| Canary host | Native maintainer-operated Linux host `alex-kycortex` | Preflight provider health captured on the maintainer Linux host before traffic, and expansion provider health refreshed on the same host before broader admission | confirmed |
| Provider set | OpenAI `gpt-4o-mini`, Anthropic `claude-haiku-4-5-20251001`, and Ollama `qwen2.5-coder:7b` at `http://127.0.0.1:11434` | Preflight provider health was healthy for all three providers at `2026-04-13T02:34:45.948542+00:00`; expansion provider health remained healthy at `2026-04-13T02:47:53.463682+00:00`; OpenAI and Anthropic were externally validated cleanly; Ollama triggered a code-validation incident at `2026-04-13T02:49:28.144777+00:00` because the generated artifact omitted `main()` | confirmed preflight / abort triggered on Ollama |
| Persistence backend | Same persisted `ProjectState` backend and artifact retention used by the live canary class | File-backed `ProjectState` JSON persisted under `/home/tupira/Dados/experiments/kycortex_agents/canary_c74e957_2026_04_13T02_34_33Z/eligible_workflows/.../project_state.json` | confirmed |
| Sandbox policy | Same sandbox restrictions as the published `v1.0.13a5` artifact | The accepted OpenAI and Anthropic checkpoints plus the aborting Ollama checkpoint all used the released candidate defaults with no environment-specific sandbox override recorded in the workflow config; generated code import validation remained sandboxed with network and subprocess access disabled | confirmed for the controlled subset |
| Release settings | Same retry, repair, and release settings as the published `v1.0.13a5` artifact | Controlled `release-user-smoke` runs used `workflow_failure_policy=continue`, `workflow_max_repair_cycles=1`, `temperature=0.0`, `max_tokens=700`, `timeout_seconds=180.0`, and Ollama `num_ctx=16384` | confirmed |
| Telemetry access | Operator can export both `snapshot()` and `internal_runtime_telemetry()` from the same persisted state | The first accepted OpenAI checkpoint and the aborting Ollama checkpoint were both exported from repository-owned state, and the abort decision remained traceable to the generated artifact validation failure | confirmed |

## Admission Outcome

The canary window opened after the live host, provider set, persistence path, and operator telemetry path were all pinned into repository-owned evidence.

Expansion preflight was refreshed successfully before broader admission, but the third controlled workflow `release_user_smoke_ollama` generated an artifact without `main()` and failed external validation.

The canary therefore froze at 3 eligible workflows and the current `v1.0.13a5` window was aborted instead of expanded further.