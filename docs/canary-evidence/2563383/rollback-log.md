# Rollback Log - 2563383

Status: rollback decision recorded and rollback baseline re-smoke validated

Planned rollback target:

- commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`
- rationale: previous published alpha release `v1.0.13a2`

## Entries

- 2026-04-12T23:16:16.292317+00:00: Canary aborted after zero-budget false success on `run_06_ollama`. No broader customer-facing traffic remained to drain, so no live environment cutover back to `v1.0.13a2` was required. Further canary admission is frozen and any resumed staging must restart from the rollback baseline after the defect is fixed.
- 2026-04-13T00:18:27.996254+00:00: Rollback baseline `v1.0.13a2` was re-smoke-validated on host `alex-kycortex` with the controlled `release-user-smoke` workflow on Ollama `qwen2.5-coder:7b` via `http://127.0.0.1:11434`. Outcome: `phase=completed`, `terminal_outcome=completed`, all 3 tasks reached `done`, `repair_cycle_count=0`, and the generated artifact `code_implementation.py` exposed both `calculate_budget_balance()` and `main()` with sample balance `2650.00`. Evidence: `validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`.