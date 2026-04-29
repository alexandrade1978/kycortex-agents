# Environment Parity - 03d6403

Status: pre-canary parity partially pinned; live admission blocked until the full provider set is clean on the current head

The canary window has not started.

This document records what is already pinned for the current head and what still blocks live admission.

| Surface | Intended setting | Current evidence | Status |
| --- | --- | --- | --- |
| Candidate identity | Commit `03d6403b58e5e2365501b144f50f90976dc1311b`, package `1.0.13a10.dev0` | Current `main` head plus green deterministic repository gate | confirmed |
| Rollback target | Commit `f99a38d1a08dceedcd0b520e302e3615f81d60f0`, tag `v1.0.13a6`, package `1.0.13a6` | Latest published known-good line with retained Phase 16 evidence in `../f99a38d/` | confirmed baseline / not activated |
| Provider set | OpenAI `gpt-4o-mini`, Anthropic `claude-haiku-4-5-20251001`, and Ollama `qwen2.5-coder:7b` on the maintainer-operated Linux host | Current-head pre-canary evidence shows `openai` clean on a fresh full-scope partial checkpoint, `ollama` clean on the active-scope `10/10` baseline, and `anthropic` failing on the first live task call with persisted provider rejection and exhausted repair budget | blocked |
| Persistence backend | Same persisted `ProjectState` JSON backend used by repository-owned empirical validation | Pre-canary evidence is pinned under `output/real_world_complex_matrix_2026_04_28_full_scope/.../project_state.json` and `output/real_world_complex_matrix_2026_04_28_head03d6403_rc_requal/.../project_state.json` | confirmed for pre-canary evidence |
| Sandbox policy | Same sandbox restrictions as the current repository release-review line | Deterministic repository gate and current-head empirical checkpoints run under the repository defaults; no live canary host override has been admitted | provisional |
| Release settings | Same retry, repair, and release settings intended for the next candidate line | Current-head partial full-scope rerun used `failure_policy=continue`, `resume_policy=resume_failed`, `max_repair_cycles=3`, `max_tokens=3200`, `ollama_num_ctx=16384`, and `ollama_timeout_seconds=900`; active-scope baseline used `resume_failed`, `continue`, and `max_repair_cycles=1` | provisional |
| Telemetry access | Operator can export both `snapshot()` and `internal_runtime_telemetry()` from the same persisted state | Current-head pre-canary checkpoint exports were derived from `ProjectState.snapshot()` and `ProjectState.internal_runtime_telemetry()` for the retained `openai`, `anthropic`, and active-scope `ollama` states | confirmed for pre-canary evidence |

## Admission Rule

Do not start the canary until Anthropic task execution is restored on the current host/provider path and a fresh full-scope `15/15` current-head qualification replaces the current partial checkpoint evidence.
