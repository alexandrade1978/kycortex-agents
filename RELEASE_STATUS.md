# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13a10.dev0`
- Latest released version: `1.0.13a6`
- Latest published release: `1.0.13a6`
- Latest published tag: `v1.0.13a6`
- Current branch for release preparation: `main`
- Active unpublished head under review: `10622f3`
- Release publish action: no publish flow is in progress; the validated local slice remains unpublished.

## Current Posture

- Published baseline remains `v1.0.13a6`; the active unpublished head is a newer local validation slice on `main`.
- The active unpublished head now satisfies the local Beta 1 minimum: deterministic validation is green, a fresh same-head full `5 x 3` matrix finished `15/15 completed/completed`, and the previously hardest repaired scenario/provider pair also has a fresh clean replay.
- Release-candidate review is not open.
- No canary claim or production-readiness claim is attached to the unpublished head.

## Repository Release Gate

- The deterministic repository release gate remains green on the active line.
- The current orchestration bugfix slice also re-cleared the touched regression envelope, including `tests/test_orchestration_support.py tests/test_project_state.py` and the focused guard tests for the latest AST and acceptance changes.
- Local backup freshness was revalidated again before publication prep using the canonical `kycortex-usb-backup.timer` and `kycortex-usb-backup.service` units.

## Next Release-Facing Action

1. Decide whether to publish the validated local slice or keep it as an unpublished Beta 1-qualified checkpoint.
2. If publication is approved, run `RELEASE.md` end-to-end on the same head.
3. Keep canary and go-live decisions separate; they remain gated beyond this local Beta 1 checkpoint.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)