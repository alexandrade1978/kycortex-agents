# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a12.dev0`
- Latest released version: `1.0.13a11`
- Latest published release: `1.0.13a11`
- Latest published tag: `v1.0.13a11`
- Current branch for release preparation: `main`
- Release candidate under canary record: `v1.0.13a11` (`1af2d8d`)
- Release publish action: no release flow is in progress.

## Current Posture

- Published package baseline is `v1.0.13a11`.
- The `1.0.13a11` release extends `1.0.13a10` with a comprehensive partial-branch coverage campaign, reaching 99.89% branch coverage (2568 tests).
- Phase 16 canary record for `v1.0.13a11` is now open under `docs/canary-evidence/1af2d8d/`.
- Canary minimum window is now satisfied and the record is awaiting explicit user authorization.
- Current canary cumulative state: `121/121` accepted workflows, `0` incidents, `0` rollbacks.
- Published daily-review evidence currently covers `2026-05-04`, `2026-05-05`, `2026-05-06`, `2026-05-07`, `2026-05-09`, `2026-05-10`, and `2026-05-11`.
- The 7-day minimum window was satisfied at `2026-05-11T05:11:04Z`; promotion remains blocked until explicit user authorization is provided.

## Repository Release Gate

- The deterministic repository release gate is green on `1af2d8d` (CI run `25299510656`, Release `25299517420`).
- `ruff`, `mypy`, and the full pytest suite (2568 tests) are clean.
- Coverage: 99.89% (23 dead-code branch misses accepted, 2 dead-code statement misses accepted).
- No release workflow is currently in progress.

## Next Release-Facing Action

1. Await explicit user decision on whether to promote `v1.0.13a11` beyond the canary posture.
2. Continue milestone engineering on `1.0.13a12.dev0` in parallel while the decision remains open.
3. Keep canary and go-live decisions separately gated until explicit authorization is provided.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)