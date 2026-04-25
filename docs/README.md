# Documentation

This index points to the stable public documentation surface for KYCortex.

## Public Entry Points

- [README.md](../README.md): product positioning, installation, quick start, and the primary public runtime surface.
- [RELEASE_STATUS.md](../RELEASE_STATUS.md): short release-state snapshot for the current branch and latest published baseline.
- [RELEASE.md](../RELEASE.md): package release procedure, validation steps, tagging, and post-publish verification.
- [CHANGELOG.md](../CHANGELOG.md): release-facing change history.
- [MIGRATION.md](../MIGRATION.md): upgrade guidance for users moving between supported public surfaces.
- [CONTRIBUTING.md](../CONTRIBUTING.md): local development workflow and contribution expectations.
- [COMMERCIAL_LICENSE.md](../COMMERCIAL_LICENSE.md): dual-license overview and commercial licensing contact path.
- [CONTRIBUTOR_RIGHTS.md](../CONTRIBUTOR_RIGHTS.md): contributor-rights expectations for the dual-licensed repository.

## Public Guides

- [architecture.md](architecture.md): stable runtime architecture, boundaries, and supported extension seams.
- [providers.md](providers.md): provider configuration, routing, health checks, and backend differences.
- [workflows.md](workflows.md): workflow model, dependency scheduling, failure policies, and resume semantics, plus adaptive prompt-policy behavior.
- [persistence.md](persistence.md): state persistence backends, resume behavior, and snapshot inspection.
- [extensions.md](extensions.md): supported customization seams for agents, providers, registries, and persistence backends.
- [troubleshooting.md](troubleshooting.md): public failure classes, diagnosis, and recovery patterns.
- [go-live-policy.md](go-live-policy.md): repository-owned policy for production-readiness claims beyond package publication.

## Public Examples

- [examples/example_simple_project.py](../examples/example_simple_project.py): minimal packaged example using the public top-level API.
- [examples/example_resume_workflow.py](../examples/example_resume_workflow.py): persisted-state resume example.
- [examples/example_custom_agent.py](../examples/example_custom_agent.py): custom-agent example using `BaseAgent` and `AgentRegistry`.
- [examples/example_multi_provider.py](../examples/example_multi_provider.py): same workflow across OpenAI, Anthropic, and Ollama.
- [examples/example_release_user_smoke.py](../examples/example_release_user_smoke.py): user-style live smoke that validates the generated Python artifact.
- [examples/example_provider_matrix_validation.py](../examples/example_provider_matrix_validation.py): full-workflow empirical validation runner across the available providers.
- [examples/example_test_mode.py](../examples/example_test_mode.py): deterministic local execution without a live provider.
- [examples/example_complex_workflow.py](../examples/example_complex_workflow.py): converging multi-parent workflow example.
- [examples/example_failure_recovery.py](../examples/example_failure_recovery.py): persisted failure-and-resume example.
- [examples/example_snapshot_inspection.py](../examples/example_snapshot_inspection.py): snapshot inspection plus the exact internal telemetry read path.

## Public API Navigation

- [kycortex_agents/config.py](../kycortex_agents/config.py): runtime configuration and provider validation.
- [kycortex_agents/orchestrator.py](../kycortex_agents/orchestrator.py): workflow execution coordinator.
- [kycortex_agents/types.py](../kycortex_agents/types.py): public typed contracts.
- [kycortex_agents/exceptions.py](../kycortex_agents/exceptions.py): public exception hierarchy.
- [kycortex_agents/agents](../kycortex_agents/agents): built-in agents and registry-based resolution.
- [kycortex_agents/providers](../kycortex_agents/providers): built-in provider implementations and shared provider abstractions.
- [kycortex_agents/memory](../kycortex_agents/memory): project state model and persistence backends.
- [kycortex_agents/workflows](../kycortex_agents/workflows): public workflow-facing module surface.

## Operational And Historical Records

The repository also contains release and canary operations material under [canary-operations.md](canary-operations.md) and [canary-evidence](canary-evidence), but those records are repository-owned operational or historical references rather than part of the primary public product documentation surface.