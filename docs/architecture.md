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
- `ProjectSnapshot`: immutable public read model used for inspection and compatibility surfaces.
- `AgentView`: filtered prompt-facing projection derived from the current task dependency closure.
- `TaskResult`, `FailureRecord`, `DecisionRecord`, and `ArtifactRecord`: normalized public result and audit structures.
- `TaskStatus` and `WorkflowStatus`: public workflow lifecycle enums.

These contracts define the stable boundary between orchestration, agents, persistence, and downstream consumers.

The active boundary split now treats four views explicitly: internal persisted workflow state is the exact resume source of truth, `ProjectSnapshot` is the public normalized read model, `AgentView` is the prompt-facing filtered projection, and `InternalRuntimeTelemetry` is the private operator surface exposed through `ProjectState.internal_runtime_telemetry()`. The local workspace now includes the full three-slice split: the `AgentView` wall is active, the dedicated internal telemetry read path is active, and the old public snapshot, public execution-event, and provider-matrix telemetry mirrors are removed.

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

Before each task runs, the orchestrator builds a context payload from the current `ProjectSnapshot` and previously completed task outputs, then serializes only `AgentView` into `context["snapshot"]`.

The context includes:

- project name and goal
- current phase and task metadata
- filtered agent-view snapshot data derived from the current task dependency closure
- completed upstream task outputs keyed by task id
- semantic aliases such as `architecture`, `code`, `review`, `tests`, `documentation`, and `legal` when they can be inferred from agent roles or task titles

This model keeps downstream tasks dependency-aware without relying on implicit global state.

`AgentView` artifact selection is intentionally deterministic so tests can lock the rule directly: an artifact record is visible when its `metadata.task_id` is absent or belongs to the current task dependency closure, and `content` is present only when that source task is a direct dependency of the current task. The direct-dependency set includes `task.dependencies`, `repair_origin_task_id`, and `repair_context["budget_decomposition_plan_task_id"]` when present.

The same dependency closure now also gates raw completed-task outputs, semantic aliases, and planned-module hints inside prompt context so unrelated finished tasks do not leak into downstream agent inputs.

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

Persisted state remains the exact resume source of truth. `ProjectSnapshot` is reconstructed from that state for public inspection and compatibility, but it is no longer the prompt-facing context wall.

## Provider Layer

The provider layer isolates backend-specific model calls from the rest of the runtime.

- `BaseLLMProvider` defines the common generation contract.
- `create_provider()` selects the configured built-in provider.
- `OpenAIProvider`, `AnthropicProvider`, and `OllamaProvider` adapt their respective backends into a shared runtime surface.

Provider-call metadata is propagated back into task state so usage, latency, and failure details survive persistence. `ProjectState.internal_runtime_telemetry()` now exposes the operator-facing runtime view with exact provider/model identities, usage, durations, latencies, repair-budget counters, and richer provider-health data. Public snapshots, public execution events, and provider-matrix summaries no longer carry those exact telemetry mirrors.

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
- agent prompts should consume `AgentView`, not raw `ProjectSnapshot`
- provider and persistence customization should use the exported interfaces instead of internal helper functions

This boundary keeps the 1.0 runtime stable while still allowing controlled extension.