# Environment Parity - 2563383

Status: live host pinned and first checkpoint recorded; canary aborted after zero-budget false-success incident on `run_06_ollama`

This document records the concrete live canary environment values that were observed before traffic started and during the first controlled checkpoint.

| Surface | Intended setting | Current evidence | Status |
| --- | --- | --- | --- |
| Candidate identity | Commit `25633830213afd029418b2a856e097b2403edc4f`, tag `v1.0.13a3`, package `1.0.13a3` | GitHub verified commit and tag, GitHub Actions CI run `#456` green, GitHub Actions Release run `#18` green | confirmed |
| Rollback target | Commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`, tag `v1.0.13a2`, package `1.0.13a2` | Previous published release plus GitHub Actions Release run `#17` green; broader traffic never advanced past the controlled canary subset, so no live cutover back to this baseline was required | confirmed baseline / not activated |
| Canary host | Native maintainer-operated Linux host `alex-kycortex` | Preflight provider health captured on `Linux-6.17.0-20-generic-x86_64-with-glibc2.39`, Python `3.12.3`, with the maintainer provider env file present before traffic | confirmed |
| Provider set | OpenAI `gpt-4o-mini`, Anthropic `claude-haiku-4-5-20251001`, and Ollama `qwen2.5-coder:7b` at `http://127.0.0.1:11434` | Preflight provider health was healthy for all three providers at `2026-04-12T23:12:49.569692Z`; the first 6 controlled workflows hit the same provider/model set | confirmed |
| Persistence backend | Same persisted `ProjectState` backend and artifact retention used by the live canary class | File-backed `ProjectState` JSON persisted under `/home/tupira/Dados/experiments/kycortex_agents/canary_2563383_2026_04_13/eligible_workflows/.../project_state.json` | confirmed |
| Sandbox policy | Same sandbox restrictions as published `v1.0.13a3` | The first checkpoint used the released candidate defaults with no environment-specific sandbox override recorded in the workflow configs | provisional but consistent |
| Release settings | Same retry, repair, and release settings as the published `v1.0.13a3` artifact | Controlled `release-user-smoke` runs used `workflow_failure_policy=continue`, `workflow_max_repair_cycles=1`, `temperature=0.0`, `max_tokens=700`, `timeout_seconds=180.0`, and Ollama `num_ctx=16384` | confirmed |
| Telemetry access | Operator can export both `snapshot()` and `internal_runtime_telemetry()` from the same persisted state | The first accepted OpenAI checkpoint and the aborting Ollama incident checkpoint were both exported from repository-owned state files | confirmed |

## Admission Outcome

The canary window opened after the live host, provider set, persistence path, and operator telemetry path were all pinned into repository-owned evidence.

Expansion is now frozen because `run_06_ollama` triggered a zero-budget false-success incident. Any resumed canary must use a fixed candidate and restart from a fresh preflight.