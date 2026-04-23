# Architecture Guide

This guide describes the current 1.0-oriented runtime architecture for `kycortex-agents` after the execution, persistence, public API stabilization, and product-positioning work.

KYCortex should be understood as an agent orchestration runtime and control plane with a developer framework layer on top. It is not just a prompt orchestration helper library, and it is not presented here as a full standalone "AI operating system". The package owns runtime execution, policy enforcement, validation, repair, and persistence while still exposing framework-style extension points for developers.

## Product Positioning

The repository maps to three complementary layers:

1. **Orchestration runtime / control plane**: executes workflows, applies retry and repair policy, routes provider/model calls, validates outputs, and persists operator-visible state.
2. **Developer framework / SDK**: exposes the supported Python APIs for custom agents, providers, workflows, configuration, and persistence backends.
3. **Regulated-workflow foundation**: provides the baseline execution substrate that domain-specific workflow packs, validation suites, and compliance-oriented product surfaces can build on.

## Runtime Layers

The package is organized into a small set of runtime layers with explicit responsibilities:

1. Public API surface: `kycortex_agents`, `config`, `types`, `exceptions`, `memory`, `providers`, and `workflows` expose the supported import paths for consumers.
2. Workflow orchestration: `kycortex_agents.orchestrator.Orchestrator` is the supported public control surface and thin runtime dispatcher for workflow execution.
3. Internal orchestration support: `kycortex_agents.orchestration.*` owns deterministic runtime behavior such as context building, validation, sandbox execution, workflow control, repair planning, AST analysis, and output normalization.
4. Agent runtime: `kycortex_agents.agents.base_agent.BaseAgent` normalizes the agent execution contract around `AgentInput` and `AgentOutput`, while concrete agents implement role-specific behavior.
5. Provider abstraction: `kycortex_agents.providers` decouples agent execution from provider backends through `BaseLLMProvider` and the built-in OpenAI, Anthropic, and Ollama implementations.
6. State and persistence: `kycortex_agents.memory.project_state.ProjectState` owns task, decision, artifact, and execution-event state, while `kycortex_agents.memory.state_store` persists that state to JSON or SQLite.

`Orchestrator` now acts as a thin public control surface and runtime dispatcher, while deterministic internal behavior is owned by modules under `kycortex_agents.orchestration`.

Adaptive prompt-policy resolution is part of this internal orchestration layer. The context-building runtime resolves a per-execution policy profile and exposes it to built-in generation agents, allowing prompt behavior to adapt by model capability and budget without changing the public workflow contract.

## Core Domain Contracts

The typed runtime revolves around the public contracts in `kycortex_agents.types`:

- `AgentInput`: validated task, project, and context payload passed into agents.
- `AgentOutput`: normalized agent result containing summary text, raw content, artifacts, decisions, and metadata.
- `ProjectSnapshot`: immutable public read model used for inspection and compatibility surfaces.
- `AgentView`: filtered prompt-facing projection derived from the current task dependency closure.
- `TaskResult`, `FailureRecord`, `DecisionRecord`, and `ArtifactRecord`: normalized public result and audit structures.
- `TaskStatus` and `WorkflowStatus`: public workflow lifecycle enums.

These contracts define the stable boundary between orchestration, agents, persistence, and downstream consumers.

The architecture treats four views explicitly: internal persisted workflow state is the exact resume source of truth, `ProjectSnapshot` is the public normalized read model, `AgentView` is the prompt-facing filtered projection, and `InternalRuntimeTelemetry` is the private operator surface exposed through `ProjectState.internal_runtime_telemetry()`. The public snapshot and execution-event surfaces intentionally avoid exact telemetry mirrors.

## Workflow Execution Model

`ProjectState` stores the workflow graph as a list of tasks with explicit dependency ids. The public orchestrator executes that graph using the following model:

1. Validate the dependency graph and agent assignments before execution starts.
2. Resume interrupted tasks and, when configured, re-queue failed tasks plus dependency-skipped descendants.
3. Select runnable tasks from the dependency graph using topological ordering rules.
4. Execute each task through the resolved agent runtime.
5. Normalize outputs into `AgentOutput`, persist artifacts and decisions, and save the project state.
6. Record structured execution events and workflow lifecycle transitions for later inspection.

Failure behavior is controlled by `workflow_failure_policy` and `workflow_resume_policy` in `KYCortexConfig`.

In the current architecture, the public method boundary is intentionally small:

- `Orchestrator.run_task(...)` resolves the agent, assembles the public runtime callbacks, delegates input construction and output validation to owner modules, and persists the normalized result
- `Orchestrator.execute_workflow(...)` assembles workflow runtime callbacks and delegates the dependency-aware workflow loop to `kycortex_agents.orchestration.workflow_control.execute_workflow_runtime(...)`
- workflow pause/resume/cancel/skip/override/replay operations remain on `Orchestrator` as the supported control surface, but each delegates directly to `workflow_control.py`

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
- internal deterministic helper behavior should flow through `kycortex_agents.orchestration.*` owner modules rather than back into `Orchestrator`
- state should be inspected through `ProjectState` or `ProjectSnapshot`
- agent prompts should consume `AgentView`, not raw `ProjectSnapshot`
- provider and persistence customization should use the exported interfaces instead of internal helper functions

This boundary keeps the 1.0 runtime stable while still allowing controlled extension.