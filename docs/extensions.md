# Extension Guide

This guide explains the supported extension seams in `kycortex-agents` and how to customize agents, registries, providers, persistence backends, and orchestrator wiring without relying on internal helpers.

## Supported Extension Surface

The public extension points are intentionally small:

- `BaseAgent` for custom agent implementations
- `AgentRegistry` for registering and resolving agent instances
- `BaseLLMProvider` for model-backend integrations
- `BaseStateStore` for custom persistence backends
- `Orchestrator` for workflow execution with a custom registry

These types are exported from the public package surface and covered by regression tests.

## Custom Agents

Subclass `BaseAgent` when you want a workflow task to execute through the standard runtime contract.

The default execution path is:

1. `validate_input()` checks the public `AgentInput`
2. `before_execute()` runs optional pre-execution hooks
3. `run_with_input()` or legacy `run()` performs the agent work
4. `_normalize_output()` converts strings into `AgentOutput`
5. `after_execute()` finalizes metadata and default artifacts

Minimal example:

```python
from kycortex_agents import BaseAgent, KYCortexConfig


class SummaryAgent(BaseAgent):
    required_context_keys = ("architecture",)

    def __init__(self, config: KYCortexConfig):
        super().__init__(name="Summary Agent", role="summarizer", config=config)

    def run(self, task_description: str, context: dict) -> str:
        architecture = context["architecture"]
        return f"Summary for {task_description}: {architecture[:200]}"
```

Use `required_context_keys` when missing upstream context should fail fast instead of degrading silently.

## Lifecycle Hooks

`BaseAgent` exposes a few public hooks for extension authors:

- `validate_input(agent_input)` to enforce additional preconditions
- `before_execute(agent_input)` for setup or instrumentation
- `after_execute(agent_input, output)` to shape the final `AgentOutput`
- `validate_output(output)` to reject malformed normalized output
- `on_execution_error(agent_input, exc)` to transform or specialize execution failures

Extensions can also call `require_context_value(agent_input, key)` when they want the same missing-context validation behavior used by the built-in runtime.

## Registry Customization

`AgentRegistry` is the supported way to bind workflow task assignments to agent instances.

- `register(key, agent)` adds or replaces a binding
- `get(key)` resolves the normalized key or raises `AgentExecutionError`
- `has(key)` checks whether a workflow assignment is valid
- `normalize_key(key)` applies the same key normalization used during execution

Example:

```python
from kycortex_agents import AgentRegistry, KYCortexConfig, Orchestrator, ProjectState, Task

config = KYCortexConfig(output_dir="./output")
registry = AgentRegistry()
registry.register("summary agent", SummaryAgent(config))

project = ProjectState(project_name="Demo", goal="Summarize architecture")
project.add_task(
    Task(
        id="summary",
        title="Create Summary",
        description="Summarize the architecture",
        assigned_to="summary_agent",
    )
)

Orchestrator(config, registry=registry).execute_workflow(project)
```

The orchestrator validates agent resolution before execution starts, so unknown assignments fail fast.

## Custom Providers

Implement `BaseLLMProvider` when you need a non-built-in model backend.

Required surface:

- `generate(system_prompt, user_message)` returns generated text
- `get_last_call_metadata()` optionally returns provider usage or timing metadata

When provider metadata is returned as a dictionary, the agent runtime propagates it into `AgentOutput` metadata, task state, and persisted execution history.

## Custom Persistence Backends

Implement `BaseStateStore` when JSON and SQLite are not enough.

Required methods:

- `save(path, data)` to persist the serialized project-state payload
- `load(path)` to return the serialized project-state payload as a dictionary

If a backend fails to save or load correctly, it should raise `StatePersistenceError` so callers get the same persistence-failure behavior as the built-in stores.

## Orchestrator Integration

The clean extension path is to keep workflow execution inside `Orchestrator` and swap collaborators around it.

- pass a custom `AgentRegistry` into `Orchestrator(config, registry=...)`
- use custom agents that inherit from `BaseAgent`
- let those agents wrap built-in or custom providers
- persist workflow state through `ProjectState.save()` and `ProjectState.load()`

This keeps dependency scheduling, retry behavior, resume behavior, and snapshot construction inside the supported runtime.

## Design Boundaries

A few extension boundaries are worth preserving:

- prefer top-level public imports from `kycortex_agents`
- do not rely on private orchestrator helpers such as internal context-building methods
- keep custom workflow execution flowing through `execute_workflow()` or `run_task()`
- keep persistence integrations at the state-store boundary instead of patching `ProjectState` internals

These boundaries let the package evolve internally without breaking supported integrations.

## Testing Extensions

Extension code should be validated at the same public boundary used by the built-in runtime.

- test custom agents through `execute()` or through an `Orchestrator`
- test registry bindings with normalized task assignments
- test custom providers by verifying generated text plus `get_last_call_metadata()` propagation
- test custom persistence backends through `ProjectState.save()`, `ProjectState.load()`, and `snapshot()` behavior

If an extension requires new public behavior, add regression coverage at the package boundary before depending on it.