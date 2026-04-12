# Documentation

This repository keeps its primary user and contributor guidance in a small set of repository-owned entry points so the 1.0 line stays easy to navigate.

## Core Entry Points

- [README.md](../README.md): installation, quick start, architecture overview, and current project status.
- [CONTRIBUTING.md](../CONTRIBUTING.md): development workflow and contribution expectations.
- [CONTRIBUTOR_RIGHTS.md](../CONTRIBUTOR_RIGHTS.md): contributor-rights expectations for a dual-licensed repository.
- [COMMERCIAL_LICENSE.md](../COMMERCIAL_LICENSE.md): dual-license overview and commercial licensing contact path.
- [RELEASE.md](../RELEASE.md): local release validation, version tagging, and post-tag verification steps.
- [RELEASE_STATUS.md](../RELEASE_STATUS.md): current release-state snapshot and next maintenance-release action.
- [scripts/release_artifact_manifest.py](../scripts/release_artifact_manifest.py): staged release artifact manifest generator and verifier used between distribution build and publish.
- [scripts/release_promotion_summary.py](../scripts/release_promotion_summary.py): promotion provenance writer used after manifest verification to bind the tag, commit, and promoted artifacts.
- [scripts/release_published_assets_check.py](../scripts/release_published_assets_check.py): post-publish GitHub release verifier that downloads the published assets for a tag and proves their checksums match the staged release evidence.
- [CHANGELOG.md](../CHANGELOG.md): release-facing summary of the repository changes shipped in the 1.0 line.
- [MIGRATION.md](../MIGRATION.md): upgrade guidance for users moving from the early prototype to the stabilized public API surface.
- [.github/workflows/release.yml](../.github/workflows/release.yml): tagged-release workflow that revalidates the repository, builds distribution artifacts, and publishes GitHub releases for version tags.
- [architecture.md](architecture.md): runtime layers, workflow execution model, persistence design, and supported extension seams.
- [go-live-policy.md](go-live-policy.md): repository-owned SLOs, error budgets, and the staged gates that separate package releases from production go-live claims.
- [canary-operations.md](canary-operations.md): repository-controlled Phase 16 operator runbook, rollback rules, escalation policy, incident templates, and canary evidence checklist.
- [canary-evidence/README.md](canary-evidence/README.md): repository-controlled root and layout rules for Phase 16 canary evidence bundles.
- [providers.md](providers.md): provider selection, backend-specific configuration, metadata behavior, and extension guidance.
- [workflows.md](workflows.md): task definitions, dependency scheduling, retry/resume behavior, and workflow troubleshooting.
- [persistence.md](persistence.md): state-file backends, save/load semantics, resume behavior, and snapshot inspection.
- [extensions.md](extensions.md): supported public customization seams for agents, registries, providers, and persistence backends.
- [troubleshooting.md](troubleshooting.md): common failure classes, audit signals, recovery paths, and persisted-state inspection.
- [examples/example_simple_project.py](../examples/example_simple_project.py): minimal packaged example using the public top-level API.
- [examples/example_resume_workflow.py](../examples/example_resume_workflow.py): persisted-state resume example using the public top-level API.
- [examples/example_custom_agent.py](../examples/example_custom_agent.py): custom-agent example using `BaseAgent` and `AgentRegistry` through the public API.
- [examples/example_multi_provider.py](../examples/example_multi_provider.py): provider-configuration example showing the same workflow across OpenAI, Anthropic, and Ollama.
- [examples/example_release_user_smoke.py](../examples/example_release_user_smoke.py): user-style live smoke example that generates a small project through the public API and validates the produced Python artifact.
- [examples/example_provider_matrix_validation.py](../examples/example_provider_matrix_validation.py): empirical provider-matrix runner that skips unavailable providers, verifies provider readiness, and writes a structured full-workflow validation summary under the current minimized public-summary contract.
- [examples/example_test_mode.py](../examples/example_test_mode.py): deterministic local execution example using fake agents instead of live provider calls.
- [examples/example_complex_workflow.py](../examples/example_complex_workflow.py): converging multi-parent workflow example showing merged artifacts and decisions flowing into a downstream task.
- [examples/example_failure_recovery.py](../examples/example_failure_recovery.py): persisted failure-and-resume example showing retry exhaustion, reload, and `resume_failed` recovery.
- [examples/example_snapshot_inspection.py](../examples/example_snapshot_inspection.py): structured snapshot-inspection example showing the public `snapshot()` read model together with `ProjectState.internal_runtime_telemetry()` for exact operator-facing telemetry, plus provider health summaries, artifacts, decisions, and execution events.

## Public API Navigation

- `kycortex_agents`: top-level public package exporting the main runtime, config, types, providers, memory, and workflow symbols.
- [kycortex_agents/config.py](../kycortex_agents/config.py): runtime configuration and provider validation.
- [kycortex_agents/orchestrator.py](../kycortex_agents/orchestrator.py): workflow execution coordinator.
- [kycortex_agents/types.py](../kycortex_agents/types.py): public typed contracts such as `AgentInput`, `AgentOutput`, `AgentView`, `TaskResult`, task and workflow statuses, and the normalized public summary shapes used by inspection helpers.
- [kycortex_agents/exceptions.py](../kycortex_agents/exceptions.py): public exception hierarchy.

## Module Guides

- [kycortex_agents/agents](../kycortex_agents/agents): built-in agent implementations, base agent behavior, and registry-based resolution.
- [kycortex_agents/providers](../kycortex_agents/providers): shared provider interface plus OpenAI, Anthropic, and Ollama provider integrations.
- [kycortex_agents/memory](../kycortex_agents/memory): project state model, persistence backends, and state-store selection.
- [kycortex_agents/workflows](../kycortex_agents/workflows): public workflow-facing module surface for orchestration imports.

## Examples And Usage

- Use the top-level package imports shown in [README.md](../README.md) for the canonical public API.
- Use the provider configuration section in [README.md](../README.md) when choosing between OpenAI, Anthropic, and Ollama runtime setup.
- Use the workflow control examples in [README.md](../README.md) when configuring task dependencies, failure policies, and resume policies.
- Use [persistence.md](persistence.md) when choosing between JSON and SQLite state files or when debugging resume behavior.
- Use [extensions.md](extensions.md) when adding custom agents, registries, providers, or persistence backends.
- Use [troubleshooting.md](troubleshooting.md) when debugging configuration failures, blocked workflows, retries, or persisted-state recovery.
- Start from [examples/example_simple_project.py](../examples/example_simple_project.py) when validating local installs or learning the workflow model.
- Use [examples/example_resume_workflow.py](../examples/example_resume_workflow.py) when learning persisted reload and resume behavior.
- Use [examples/example_custom_agent.py](../examples/example_custom_agent.py) when learning how custom agents plug into the public runtime.
- Use [examples/example_multi_provider.py](../examples/example_multi_provider.py) when comparing supported provider configurations against the same workflow definition.
- Use [examples/example_release_user_smoke.py](../examples/example_release_user_smoke.py) when you want a realistic local end-to-end creation smoke that also validates the generated Python artifact.
- Use [examples/example_provider_matrix_validation.py](../examples/example_provider_matrix_validation.py) when collecting comparable full-workflow evidence with repair cycles enabled across the currently available providers.
- Use [go-live-policy.md](go-live-policy.md) when deciding whether a successful package release is also ready for canary or production deployment.
- Use [canary-operations.md](canary-operations.md) when preparing a controlled canary rollout, documenting rollback decisions, or collecting the Phase 16 evidence packet.
- Use [canary-evidence/README.md](canary-evidence/README.md) when creating the tracked candidate directory that holds the canary evidence bundle for a specific SHA.
- Use [examples/example_test_mode.py](../examples/example_test_mode.py) when validating workflow behavior locally without calling a live provider.
- Use [examples/example_complex_workflow.py](../examples/example_complex_workflow.py) when learning how converging DAGs expose merged upstream artifacts and decisions to a downstream agent.
- Use [examples/example_failure_recovery.py](../examples/example_failure_recovery.py) when learning how persisted failed workflows reload and continue under `workflow_resume_policy="resume_failed"`.
- Use [examples/example_snapshot_inspection.py](../examples/example_snapshot_inspection.py) when learning how `snapshot()` exposes structured task results, artifacts, decisions, and execution events while exact operator-facing observability comes from `ProjectState.internal_runtime_telemetry()`.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) for repository setup plus focused public-API, packaging/docs, and full-suite test commands before making changes.
- Use [CONTRIBUTOR_RIGHTS.md](../CONTRIBUTOR_RIGHTS.md) when you need the repository's contributor-rights policy for dual-licensed maintenance.
- Use [COMMERCIAL_LICENSE.md](../COMMERCIAL_LICENSE.md) when you need the repository's dual-license overview or the contact path for commercial terms.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) for the repository `Makefile` targets and shared `.editorconfig` defaults when working locally.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) for local `ruff` and `mypy` validation commands when checking the package and examples before opening a pull request.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) for the repository coverage gate command when validating release-readiness against the maintained package coverage threshold.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) and [scripts/release_check.py](../scripts/release_check.py) for the repository release validation pass before tagging a version or triggering the release workflow.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) and [scripts/release_metadata_check.py](../scripts/release_metadata_check.py) when validating version alignment and release-facing metadata before a tag is created.
- Use [RELEASE.md](../RELEASE.md) when preparing a version tag, reviewing the final release gate, or verifying the post-tag GitHub release workflow results.
- Use [RELEASE_STATUS.md](../RELEASE_STATUS.md) when checking the repository's current release-readiness state before deciding whether to update the version and tag a release.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) for the repository `.pre-commit-config.yaml` workflow when installing local hooks or running pre-commit and pre-push automation before publishing changes.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) and [.github/workflows/ci.yml](../.github/workflows/ci.yml) when you need the repository CI baseline for pull requests, pushes to `main`, or GitHub-hosted lint/type/test verification.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) and [scripts/package_check.py](../scripts/package_check.py) when validating built wheel and source-distribution artifacts, including an already-built staged `dist/` directory, before publishing releases or changing packaging metadata.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) and [scripts/release_artifact_manifest.py](../scripts/release_artifact_manifest.py) when generating or verifying the staged release artifact manifest attached to tagged releases.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) and [scripts/release_promotion_summary.py](../scripts/release_promotion_summary.py) when generating the promotion provenance packet that binds the verified manifest to the release tag and promoted artifacts.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) and [scripts/release_published_assets_check.py](../scripts/release_published_assets_check.py) when verifying that the published GitHub release for a tag exposes the same attached asset set staged in `dist/` and that the downloaded wheel and source distribution match the attached manifest checksums.
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) and [.github/workflows/release.yml](../.github/workflows/release.yml) when preparing manual release dry runs or publishing tagged GitHub releases with attached wheel and source-distribution artifacts.
- Use [CHANGELOG.md](../CHANGELOG.md) and [MIGRATION.md](../MIGRATION.md) when preparing release notes or explaining the stabilized public surface to users migrating from earlier prototype revisions.

## Environment Variables

| Provider | Environment Variable | Requirement | Notes |
| --- | --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | Required unless `api_key` is passed directly | Used when `llm_provider="openai"`. |
| Anthropic | `ANTHROPIC_API_KEY` | Required unless `api_key` is passed directly | Used when `llm_provider="anthropic"`. |
| Ollama | None | Not required | Uses `base_url="http://localhost:11434"` by default. |

These values mirror the provider mappings and defaults exported by `kycortex_agents.config`.

## Current Release State

The next alpha candidate is `1.0.13a2`, while the latest released baseline remains `1.0.13a1`.

The current local architecture state reflects the completed runtime/public boundary split: prompt-facing context uses `AgentView`, `snapshot()` remains the public normalized read model, `ProjectState.internal_runtime_telemetry()` provides the dedicated internal operator-facing telemetry read path, and the public snapshot, public execution events, and provider-matrix summaries no longer expose the old exact telemetry mirrors.

The maintained release track still includes coverage-gate enforcement, release-metadata validation, staged artifact smoke validation, staged artifact-manifest verification, promotion-summary provenance, repository-owned published-asset checksum verification, and the tagged GitHub release workflow used to publish repository-safe package artifacts.

The repository now also keeps a separate go-live policy: release publication remains package-focused, while production deployment claims must satisfy the SLO, error-budget, and staged go-live gates in [go-live-policy.md](go-live-policy.md).

Use `snapshot()` for public inspection and `ProjectState.internal_runtime_telemetry()` for exact operator or UI observability.