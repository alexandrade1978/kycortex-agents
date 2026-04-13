# Validation Artifacts - 2563383

This directory is reserved for the retained generated artifacts and validation outputs that explain the canary decision for candidate `2563383`.

Current state:

- the live preflight provider-health checkpoint is recorded in `preflight-provider-health-2026-04-12T23-12-49Z.json`
- the first controlled canary checkpoint through the aborting `run_06_ollama` incident is recorded in `checkpoint-through-run-06-2026-04-12T23-16-16Z.json`
- the rollback-baseline re-smoke for `v1.0.13a2` is recorded in `rollback-smoke-v1.0.13a2-2026-04-13T00-18-10Z.json`
- the current published baseline still depends on retained repository-owned evidence from the clean Phase 15 matrix, GitHub Actions CI run `#456`, GitHub Actions Release run `#18`, and GitHub release `v1.0.13a3`
- the canary window was aborted before the minimum evidence window completed, so this directory currently stores the abort evidence packet rather than a completed canary close-out set

Before Phase 16 can close, copy or export the canary-window validation artifacts needed to explain accepted workflows, any recovered failures, and any rollback decision.