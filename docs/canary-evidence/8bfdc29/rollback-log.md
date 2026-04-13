# Rollback Log - 8bfdc29

Status: rollback decision recorded; no live cutover required

Planned rollback target:

- commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`
- rationale: previous known-good alpha release `v1.0.13a2`

## Entries

- 2026-04-13T00:56:30Z: Fresh `v1.0.13a4` canary window opened with rollback target pinned to `v1.0.13a2`. Historical release `v1.0.13a3` remains excluded as a rollback candidate because the zero-budget false-success incident is retained in `../2563383/`, and the same-host rollback re-smoke evidence remains `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`.
- 2026-04-13T01:34:53.543209+00:00: Canary aborted after code-validation incident on `run_04_openai`. No broader customer-facing traffic remained to drain, so no live environment cutover back to `v1.0.13a2` was required. Further canary admission is frozen and any resumed staging must use a fixed candidate plus fresh preflight. Retained rollback evidence remains `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`.