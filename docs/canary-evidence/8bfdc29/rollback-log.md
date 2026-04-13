# Rollback Log - 8bfdc29

Status: no rollback executed in the current window

Planned rollback target:

- commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`
- rationale: previous known-good alpha release `v1.0.13a2`

## Entries

- 2026-04-13T00:56:30Z: Fresh `v1.0.13a4` canary window opened with rollback target pinned to `v1.0.13a2`. Historical release `v1.0.13a3` remains excluded as a rollback candidate because the zero-budget false-success incident is retained in `../2563383/`.
- 2026-04-13T00:57:23.746148+00:00: No rollback executed after the first accepted workflow. The window remains within policy, and expansion stays on the smallest controlled subset pending the next checkpoint.