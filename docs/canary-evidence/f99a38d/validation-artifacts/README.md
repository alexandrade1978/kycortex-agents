# Validation Artifacts - f99a38d

This directory is reserved for the retained generated artifacts and validation outputs that explain the canary decision for candidate `f99a38d`.

Current state:

- the live preflight provider-health checkpoint is recorded in `preflight-provider-health-2026-04-13T03-25-21Z.json`
- the first controlled canary checkpoint is recorded in `checkpoint-first-accepted-2026-04-13T03-26-22Z.json`
- the approved rollback target `v1.0.13a2` still depends on the retained rollback re-smoke evidence in `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`
- the current published baseline also depends on retained repository-owned evidence from the clean Phase 15 matrix, the local `python scripts/release_check.py` pass, GitHub Actions Release workflow `#21`, and GitHub release `v1.0.13a6`
- the active canary window is still open, so this directory currently stores the preflight packet and the first accepted checkpoint rather than a completed close-out set

Before Phase 16 can close, copy or export the canary-window validation artifacts needed to explain accepted workflows, any recovered failures, and any rollback decision.