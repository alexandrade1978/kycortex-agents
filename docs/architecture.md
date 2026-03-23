# Architecture Guide

This guide describes the current 1.0-oriented runtime architecture for `kycortex-agents` after the execution, persistence, and public API stabilization work completed in earlier phases.

## Runtime Layers

The package is organized into a small set of runtime layers with explicit responsibilities:

1. Public API surface: `kycortex_agents`, `config`, `types`, `exceptions`, `memory`, `providers`, and `workflows` expose the supported import paths for consumers.
2. Workflow orchestration: `kycortex_agents.orchestrator.Orchestrator` validates agent resolution, builds execution context, runs dependency-aware workflows, and records workflow/task events.
3. Agent runtime: `kycortex_agents.agents.base_agent.BaseAgent` normalizes the agent execution contract around `AgentInput` and `AgentOutput`, while concrete agents implement role-specific behavior.
4. Provider abstraction: `kycortex_agents.providers` decouples agent execution from provider backends through `BaseLLMProvider` and the built-in OpenAI, Anthropic, and Ollama implementations.
5. State and persistence: `kycortex_agents.memory.project_state.ProjectState` owns task, decision, artifact, and execution-event state, while `kycortex_agents.memory.state_store` persists that state to JSON or SQLite.

## Core Domain Contracts

The typed runtime revolves around the public contracts in `kycortex_agents.types`:

- `AgentInput`: validated task, project, and context payload passed into agents.
- `AgentOutput`: normalized agent result containing summary text, raw content, artifacts, decisions, and metadata.
- `ProjectSnapshot`: immutable orchestration snapshot used for downstream context assembly and inspection.
- `TaskResult`, `FailureRecord`, `DecisionRecord`, and `ArtifactRecord`: normalized public result and audit structures.
- `TaskStatus` and `WorkflowStatus`: public workflow lifecycle enums.

These contracts define the stable boundary between orchestration, agents, persistence, and downstream consumers.

## Workflow Execution Model

`ProjectState` stores the workflow graph as a list of tasks with explicit dependency ids. The orchestrator executes that graph using the following model:

1. Validate the dependency graph and agent assignments before execution starts.
2. Resume interrupted tasks and, when configured, re-queue failed tasks plus dependency-skipped descendants.
3. Select runnable tasks from the dependency graph using topological ordering rules.
4. Execute each task through the resolved agent runtime.
5. Normalize outputs into `AgentOutput`, persist artifacts and decisions, and save the project state.
6. Record structured execution events and workflow lifecycle transitions for later inspection.

Failure behavior is controlled by `workflow_failure_policy` and `workflow_resume_policy` in `KYCortexConfig`.

## Context Assembly

Before each task runs, the orchestrator builds a context payload from the current `ProjectSnapshot` and previously completed task outputs.

The context includes:

- project name and goal
- current phase and task metadata
- full normalized snapshot data
- completed upstream task outputs keyed by task id
- semantic aliases such as `architecture`, `code`, `review`, `tests`, `documentation`, and `legal` when they can be inferred from agent roles or task titles

This model keeps downstream tasks dependency-aware without relying on implicit global state.

## Persistence Model

`ProjectState.save()` delegates to a pluggable state-store backend selected by the state file extension:

- `.json` files use `JsonStateStore`
- `.sqlite` and `.db` files use `SqliteStateStore`

Persisted state includes:

- task lifecycle status, retry counts, timestamps, and history
- structured task outputs and failure diagnostics
- project-level decisions and artifacts
- provider-call metadata and execution-event audit trails
- workflow lifecycle timestamps such as started, finished, resumed, and updated times

This persistence model supports deterministic reload, resume, and snapshot reconstruction across backends.

## Provider Layer

The provider layer isolates backend-specific model calls from the rest of the runtime.

- `BaseLLMProvider` defines the common generation contract.
- `create_provider()` selects the configured built-in provider.
- `OpenAIProvider`, `AnthropicProvider`, and `OllamaProvider` adapt their respective backends into a shared runtime surface.

Provider-call metadata is propagated back into task state and snapshots so usage, latency, and failure details survive persistence.

## Extension Points

The primary supported extension seams are:

- `BaseAgent` for custom agent implementations
- `AgentRegistry` for registering or replacing agent instances
- `BaseLLMProvider` for custom provider integrations
- `BaseStateStore` for custom persistence backends

These seams are part of the supported public API and are covered by regression tests.

## Architecture Boundaries

The package intentionally separates public contracts from internal helper behavior:

- consumers should prefer top-level imports from `kycortex_agents`
- workflow execution should flow through `Orchestrator`
- state should be inspected through `ProjectState` or `ProjectSnapshot`
- provider and persistence customization should use the exported interfaces instead of internal helper functions

This boundary keeps the 1.0 runtime stable while still allowing controlled extension.