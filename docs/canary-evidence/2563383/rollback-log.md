# Rollback Log - 2563383

Status: rollback decision recorded

Planned rollback target:

- commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`
- rationale: previous published alpha release `v1.0.13a2`

## Entries

- 2026-04-12T23:16:16.292317+00:00: Canary aborted after zero-budget false success on `run_06_ollama`. No broader customer-facing traffic remained to drain, so no live environment cutover back to `v1.0.13a2` was required. Further canary admission is frozen and any resumed staging must restart from the rollback baseline after the defect is fixed.