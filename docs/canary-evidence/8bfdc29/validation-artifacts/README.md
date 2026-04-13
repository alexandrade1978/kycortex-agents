# Validation Artifacts - 8bfdc29

This directory is reserved for the retained generated artifacts and validation outputs that explain the canary decision for candidate `8bfdc29`.

Current state:

- the live preflight provider-health checkpoint is recorded in `preflight-provider-health-2026-04-13T00-56-52Z.json`
- the first controlled canary checkpoint remains recorded in `checkpoint-first-accepted-2026-04-13T00-57-23Z.json`
- the refreshed pre-expansion provider-health checkpoint is recorded in `expansion-provider-health-2026-04-13T01-28-52Z.json`
- the aborting canary checkpoint through `run_04_openai` is recorded in `checkpoint-through-run-04-2026-04-13T01-34-53Z.json`
- the approved rollback target `v1.0.13a2` still depends on the retained rollback re-smoke evidence in `../2563383/validation-artifacts/rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`
- the current published baseline also depends on retained repository-owned evidence from the clean Phase 15 matrix, GitHub Actions CI run `#460`, GitHub Actions Release run `#19`, and GitHub release `v1.0.13a4`
- the canary window was aborted before the minimum evidence window completed, so this directory currently stores the preflight packet, expansion health refresh, and abort evidence packet rather than a completed canary close-out set

Before Phase 16 can close, copy or export the canary-window validation artifacts needed to explain accepted workflows, any recovered failures, and any rollback decision.