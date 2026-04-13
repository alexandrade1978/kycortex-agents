# Validation Artifacts - c74e957

This directory is reserved for the retained generated artifacts and validation outputs that explain the canary decision for candidate `c74e957`.

Current state:

- the live preflight provider-health checkpoint is recorded in `preflight-provider-health-2026-04-13T02-34-45Z.json`
- the first controlled canary checkpoint is recorded in `checkpoint-first-accepted-2026-04-13T02-35-04Z.json`
- the approved rollback target `v1.0.13a2` still depends on the retained rollback re-smoke evidence in `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`
- the current published baseline also depends on retained repository-owned evidence from the clean Phase 15 matrix, the local `python scripts/release_check.py` pass, GitHub Actions Release workflow `#20`, and GitHub release `v1.0.13a5`
- the active canary window is still open, so this directory currently stores the preflight packet and the first accepted checkpoint rather than a completed close-out set

Before Phase 16 can close, copy or export the canary-window validation artifacts needed to explain accepted workflows, any recovered failures, and any rollback decision.