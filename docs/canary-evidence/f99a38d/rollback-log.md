# Rollback Log - f99a38d

Status: no rollback executed through the current 100-workflow checkpoint and first daily review

Planned rollback target:

- commit `b2dc9931d12c5d31651a97bba8c99e767b582ff8`
- tag `v1.0.13a2`
- rationale: last published known-good alpha line with retained same-host rollback re-smoke evidence

## Entries

- 2026-04-13T03:25:21Z: Fresh `v1.0.13a6` canary window opened with rollback target pinned to `v1.0.13a2`. Historical releases `v1.0.13a3`, `v1.0.13a4`, and `v1.0.13a5` remain excluded as continuation candidates because the retained abort evidence lives in `../2563383/`, `../8bfdc29/`, and `../c74e957/`.
- 2026-04-13T03:26:22.839835+00:00: No rollback executed after the first accepted workflow. The window remains within policy, and expansion stays on the smallest controlled subset pending the next checkpoint.
- 2026-04-13T03:55:23.377066+00:00: No rollback executed through the 10-eligible-workflow checkpoint. The controlled subset expansion stayed within policy, so rollback remains pinned but inactive.
- 2026-04-13T04:08:17.863018+00:00: No rollback executed through the 25-eligible-workflow checkpoint. The continued expansion stayed within policy, so rollback remains pinned but inactive.
- 2026-04-13T04:22:59.352947+00:00: No rollback executed through the 50-eligible-workflow checkpoint. The continued expansion stayed within policy, so rollback remains pinned but inactive.
- 2026-04-13T10:39:05.274887+00:00: No rollback executed through the 100-eligible-workflow checkpoint. The continued expansion stayed within policy, so rollback remains pinned but inactive.
- 2026-04-13T04:30:01.447970+00:00: No rollback executed at the first same-day daily review. The window remains inside policy and the rollback target stays pinned but inactive.