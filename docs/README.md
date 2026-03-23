# Documentation

This repository keeps its primary user and contributor guidance in a small set of repository-owned entry points while the larger documentation rewrite remains in the roadmap.

## Core Entry Points

- [README.md](../README.md): installation, quick start, architecture overview, and current project status.
- [CONTRIBUTING.md](../CONTRIBUTING.md): development workflow and contribution expectations.
- [architecture.md](architecture.md): runtime layers, workflow execution model, persistence design, and supported extension seams.
- [providers.md](providers.md): provider selection, backend-specific configuration, metadata behavior, and extension guidance.
- [workflows.md](workflows.md): task definitions, dependency scheduling, retry/resume behavior, and workflow troubleshooting.
- [persistence.md](persistence.md): state-file backends, save/load semantics, resume behavior, and snapshot inspection.
- [extensions.md](extensions.md): supported public customization seams for agents, registries, providers, and persistence backends.
- [troubleshooting.md](troubleshooting.md): common failure classes, audit signals, recovery paths, and persisted-state inspection.
- [examples/example_simple_project.py](../examples/example_simple_project.py): minimal packaged example using the public top-level API.
- [examples/example_resume_workflow.py](../examples/example_resume_workflow.py): persisted-state resume example using the public top-level API.
- [examples/example_custom_agent.py](../examples/example_custom_agent.py): custom-agent example using `BaseAgent` and `AgentRegistry` through the public API.

## Public API Navigation

- `kycortex_agents`: top-level public package exporting the main runtime, config, types, providers, memory, and workflow symbols.
- [kycortex_agents/config.py](../kycortex_agents/config.py): runtime configuration and provider validation.
- [kycortex_agents/orchestrator.py](../kycortex_agents/orchestrator.py): workflow execution coordinator.
- [kycortex_agents/types.py](../kycortex_agents/types.py): public typed contracts such as `AgentInput`, `AgentOutput`, `ProjectSnapshot`, and workflow statuses.
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
- Use [CONTRIBUTING.md](../CONTRIBUTING.md) for repository setup plus focused public-API, packaging/docs, and full-suite test commands before making changes.

## Environment Variables

| Provider | Environment Variable | Requirement | Notes |
| --- | --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | Required unless `api_key` is passed directly | Used when `llm_provider="openai"`. |
| Anthropic | `ANTHROPIC_API_KEY` | Required unless `api_key` is passed directly | Used when `llm_provider="anthropic"`. |
| Ollama | None | Not required | Uses `base_url="http://localhost:11434"` by default. |

These values mirror the provider mappings and defaults exported by `kycortex_agents.config`.

## Planned Expansion

Phase 11 is expanding the example suite and developer experience beyond the current simple workflow, persisted-resume, and custom-agent examples.