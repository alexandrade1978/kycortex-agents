# Release Status

This file is the short repository-owned snapshot of the current release posture for KYCortex.

## Current Snapshot

- Package version in `pyproject.toml`: `1.0.13b2`
- Latest released version: `1.0.13b2`
- Latest published release: `1.0.13b2`
- Latest published tag: `v1.0.13b2`
- Current branch for release preparation: `main`
- Release candidate under canary record: active `docs/canary-evidence/1e68a8b/` bundle for `v1.0.13b2`
- Release publish action: no release flow is in progress.

## Current Posture

- Published package baseline is now `v1.0.13b2`.
- The `1.0.13b2` beta release extends `1.0.13b1` with a safer default completion budget for `release-user-smoke` and explicit `--max-tokens` override support for future canary tuning.
- The retained Phase 16 canary bundle for `v1.0.13a11` remains at `docs/canary-evidence/1af2d8d/` as historical evidence and is explicitly superseded by the `v1.0.13a12` publication path.
- The candidate-specific beta canary bundle for `c17c749` / `v1.0.13b1` is now on policy hold after the early window reached only `10/11` accepted workflows, retained one `code_validation` incident, and stayed below the `>=95.0%` accepted-workflow target.
- The replacement beta canary evidence at `docs/canary-evidence/1e68a8b/` now spans the clean `100-workflows` checkpoint plus `daily-review day-1` through `daily-review day-7`, closing Phase 16 as `canary-ready` at `124/125` accepted workflows, `1` retained retryable `provider_transient` incident, and `0` rollbacks.
- The minimum canary window in `docs/go-live-policy.md` is satisfied for `1e68a8b`: the candidate exceeded both `100` eligible workflows and `7` consecutive days of controlled canary observation, and the publication follow-on CI for `282024c` and `b79f22b` completed successfully.
- Same-candidate canary expansion remains frozen on `c17c749`; the active path is fresh canary admission on `1.0.13b2`.
- Production go-live is now explicitly signed off for the documented single-maintainer deployment class on `1e68a8b` / `v1.0.13b2`; the retained rollback target `v1.0.13a12` has been re-smoke-validated, the current single-maintainer support model plus release-ownership path are documented, and GitHub Actions CI run `26093363117` for commit `a067726` closed `success` before sign-off was recorded.

## Repository Release Gate

- The deterministic repository release gate stayed green on published candidate `1.0.13b2`.
- Both `scripts/release_check.py` and `make release-check` passed on the frozen `1.0.13b2` candidate before tagging.
- The GitHub prerelease for `v1.0.13b2` published the wheel, source distribution, `release-artifact-manifest.json`, and `release-promotion-summary.json`.
- Remote verification completed successfully for published commit `1e68a8b`: CI `25665805838` and Release `25665819510` both closed green.
- The current canary evidence for `c17c749` remains retained historical hold evidence for the superseded `v1.0.13b1` candidate.
- The published `100-workflows` checkpoint commit `21df7d0` completed CI run `25670557761` successfully.
- The published `daily-review day-1` commit `55356c7` completed CI run `25671181902` successfully.
- The replacement candidate `1e68a8b` / `v1.0.13b2` recorded `daily-review day-1` at `2026-05-11T12:41:39Z` with cumulative `103/104` accepted workflows, one isolated retryable `provider_transient` incident on `anthropic=many_expenses` recovered on targeted replay, and `0` rollbacks.
- The same-day follow-up review at `2026-05-11T12:58:41Z` added clean `smoke37` evidence on all three providers and advanced the cumulative window to `106/107` accepted workflows while preserving the same single retained incident.
- `daily-review day-2` at `2026-05-12T10:52:48Z` then added clean `smoke38` evidence on all three providers and advanced the cumulative window to `109/110` accepted workflows with no new incident.
- `daily-review day-3` at `2026-05-13T19:52:04Z` then added clean `smoke39` evidence on all three providers and advanced the cumulative window to `112/113` accepted workflows with no new incident.
- `daily-review day-4` at `2026-05-14T14:20:59Z` then added clean `smoke40` evidence on all three providers and advanced the cumulative window to `115/116` accepted workflows with no new incident.
- `daily-review day-5` at `2026-05-15T16:08:20Z` then added clean `smoke41` evidence on all three providers and advanced the cumulative window to `118/119` accepted workflows with no new incident.
- `daily-review day-6` at `2026-05-17T03:53:02Z` then added clean `smoke42` evidence on all three providers and advanced the cumulative window to `121/122` accepted workflows with no new incident.
- `daily-review day-7` at `2026-05-18T21:30:23Z` then added clean `smoke43` evidence on all three providers and advanced the cumulative window to `124/125` accepted workflows with no new incident.
- The follow-on CI runs for the day-7 publication commits both closed green: `282024c` in CI run `26061838993` and `b79f22b` in CI run `26063423049`.
- No release workflow is currently in progress.

## Next Release-Facing Action
1. Maintain the signed-off production deployment claim only for the documented single-maintainer deployment class.
2. Open a new repository-controlled qualification update before expanding the claim to any broader deployment class or support model.
3. Keep `README.md`, `CHANGELOG.md`, and the candidate bundle synchronized with any future deployment-claim change.

## Canonical References

- [RELEASE.md](RELEASE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [MIGRATION.md](MIGRATION.md)
- [docs/go-live-policy.md](docs/go-live-policy.md)