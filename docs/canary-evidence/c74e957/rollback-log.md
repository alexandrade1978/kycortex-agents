# Rollback Log - c74e957

Status: rollback decision recorded; no live cutover required

Planned rollback target:

- commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`
- tag `v1.0.13a2`
- rationale: last published known-good alpha line with retained same-host rollback re-smoke evidence

## Entries

- 2026-04-13T02:34:33Z: Fresh `v1.0.13a5` canary window opened with rollback target pinned to `v1.0.13a2`. Historical releases `v1.0.13a3` and `v1.0.13a4` remain excluded as continuation candidates because the retained abort evidence lives in `../2563383/` and `../8bfdc29/`.
- 2026-04-13T02:49:28.144777+00:00: Canary aborted after code-validation incident on `release_user_smoke_ollama`. No broader customer-facing traffic remained to drain, so no live environment cutover back to `v1.0.13a2` was required. Further canary admission is frozen and any resumed staging must use a fixed candidate plus fresh preflight. Retained rollback evidence remains `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`.