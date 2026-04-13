# Rollback Log - c74e957

Status: no rollback executed in the current window

Planned rollback target:

- commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`
- tag `v1.0.13a2`
- rationale: last published known-good alpha line with retained same-host rollback re-smoke evidence

## Entries

- 2026-04-13T02:34:33Z: Fresh `v1.0.13a5` canary window opened with rollback target pinned to `v1.0.13a2`. Historical releases `v1.0.13a3` and `v1.0.13a4` remain excluded as continuation candidates because the retained abort evidence lives in `../2563383/` and `../8bfdc29/`.
- 2026-04-13T02:35:04.405705+00:00: No rollback executed after the first accepted workflow. The window remains within policy, and expansion stays on the smallest controlled subset pending the next checkpoint.