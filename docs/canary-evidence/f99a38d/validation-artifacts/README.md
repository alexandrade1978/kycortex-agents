# Validation Artifacts - f99a38d

This directory is reserved for the retained generated artifacts and validation outputs that explain the canary decision for candidate `f99a38d`.

Current state:

- the live preflight provider-health checkpoint is recorded in `preflight-provider-health-2026-04-13T03-25-21Z.json`
- the broader-admission provider-health checkpoint is recorded in `expansion-provider-health-2026-04-13T03-51-37Z.json`
- the second broader-admission provider-health checkpoint is recorded in `expansion-provider-health-2026-04-13T04-03-29Z.json`
- the third broader-admission provider-health checkpoint is recorded in `expansion-provider-health-2026-04-13T04-15-41Z.json`
- the fourth broader-admission provider-health checkpoint is recorded in `expansion-provider-health-2026-04-13T09-22-33Z.json`
- the fifth broader-admission provider-health checkpoint is recorded in `expansion-provider-health-2026-04-13T09-41-39Z.json`
- the first controlled canary checkpoint is recorded in `checkpoint-first-accepted-2026-04-13T03-26-22Z.json`
- the clean checkpoint through 10 eligible workflows is recorded in `checkpoint-through-run-10-2026-04-13T04-06-06Z.json`
- the clean checkpoint through 25 eligible workflows is recorded in `checkpoint-through-run-25-2026-04-13T04-08-17Z.json`
- the clean checkpoint through 50 eligible workflows is recorded in `checkpoint-through-run-50-2026-04-13T04-30-01Z.json`
- the clean checkpoint through 100 eligible workflows is recorded in `checkpoint-through-run-100-2026-04-13T10-40-58Z.json`
- the first same-day daily review is recorded in `daily-review-2026-04-13.md`
- the approved rollback target `v1.0.13a2` still depends on the retained rollback re-smoke evidence in `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`
- the current published baseline also depends on retained repository-owned evidence from the clean Phase 15 matrix, the local `python scripts/release_check.py` pass, GitHub Actions Release workflow `#21`, and GitHub release `v1.0.13a6`
- the active canary window is still open, so this directory currently stores the preflight packet, five expansion health refreshes, the clean 10-workflow, 25-workflow, 50-workflow, and 100-workflow checkpoints, and the first same-day daily review rather than a completed close-out set

Before Phase 16 can close, copy or export the canary-window validation artifacts needed to explain accepted workflows, any recovered failures, and any rollback decision.