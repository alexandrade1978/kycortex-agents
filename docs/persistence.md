# Persistence Guide

This guide explains how workflow state is persisted in `kycortex-agents`, how the built-in backends are selected, and how persisted state supports resume, inspection, and backward-compatible reload.

## Persistence Model

`ProjectState` is the public workflow state object. It owns the mutable state that changes while a workflow runs:

- task definitions and lifecycle status
- retry counts, errors, timestamps, and transition history
- structured task outputs and provider-call metadata
- project-level decisions, artifacts, and execution events
- workflow lifecycle timestamps such as started, finished, resumed, and updated times

`ProjectState.save()` serializes that state through the configured state-store backend, and `ProjectState.load(path)` restores it into the current runtime dataclasses.

## Backend Selection

The built-in backend is selected by the `state_file` path extension through `resolve_state_store(path)`.

- `.json` uses `JsonStateStore`
- `.sqlite` and `.db` use `SqliteStateStore`
- any other extension falls back to `JsonStateStore`

This keeps backend selection explicit without adding another configuration switch.

## JSON Backend

`JsonStateStore` is the lightweight file-based backend.

- saves project state as formatted JSON
- creates missing parent directories automatically
- writes to a temporary file first and replaces the target atomically
- raises `StatePersistenceError` for missing files, invalid JSON, or failed writes

This backend is the simplest choice for local development and inspection because the state file remains directly readable.

## SQLite Backend

`SqliteStateStore` is the durable transactional backend.

- stores the latest serialized payload in a `project_state` table
- overwrites the single canonical row transactionally
- creates missing parent directories automatically
- raises `StatePersistenceError` for missing files, invalid schema, SQLite errors, or malformed persisted payloads

This backend is useful when consumers want a more durable local store without introducing external infrastructure.

## Save And Load Lifecycle

The normal persistence lifecycle is:

1. create a `ProjectState` with a chosen `state_file`
2. execute work through `Orchestrator`
3. let the runtime call `project.save()` after task and workflow transitions
4. reload with `ProjectState.load(path)` when execution needs to resume or state needs to be inspected later

Example:

```python
from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task

config = KYCortexConfig(output_dir="./output")
project = ProjectState(
    project_name="Demo",
    goal="Build demo",
    state_file="./state/project_state.sqlite",
)

project.add_task(
    Task(
        id="arch",
        title="Architecture",
        description="Design the system architecture",
        assigned_to="architect",
    )
)

Orchestrator(config).execute_workflow(project)

reloaded = ProjectState.load("./state/project_state.sqlite")
snapshot = reloaded.snapshot()
```

## Resume And Recovery

Persistence is what makes resume behavior deterministic across processes.

- `resume_interrupted_tasks()` re-queues tasks that were left in `RUNNING`
- `resume_failed_tasks()` re-queues failed tasks and dependency-skipped descendants when `workflow_resume_policy="resume_failed"`
- `skip_dependent_tasks()` records dependency-driven skips so downstream resume behavior can distinguish them from manual skips

`Orchestrator.execute_workflow()` applies these hooks before normal scheduling begins, then keeps saving state after retries, failures, skips, and completions.

## Snapshot Inspection

`ProjectState.snapshot()` returns a normalized `ProjectSnapshot` built from persisted state.

That snapshot exposes:

- `task_results` with `TaskResult`, `AgentOutput`, and `FailureRecord` data
- normalized `DecisionRecord` and `ArtifactRecord` collections
- workflow lifecycle timestamps and overall `WorkflowStatus`
- durable execution-event audit trails for workflow and task transitions

This is the preferred read model for inspection code because it normalizes legacy payloads and backend-specific storage details.

## Legacy Compatibility

`ProjectState.load()` normalizes older persisted payloads so the runtime can keep loading historical state files.

Current compatibility behavior includes:

- inferring missing decision timestamps
- filling missing artifact timestamps deterministically
- preserving legacy string-only artifacts
- reconstructing structured outputs when only raw task text exists
- inferring legacy skip-reason types when older state files predate explicit skip metadata
- filtering malformed persisted decision and output entries instead of crashing snapshot reconstruction

This keeps the persistence layer tolerant of earlier saved states while still exposing the current public snapshot model.

## Failure Modes

Persistence failures are normalized into `StatePersistenceError`.

Common failure cases include:

- loading a missing state file
- loading invalid JSON
- loading invalid SQLite schema or malformed SQLite payloads
- write failures during atomic replacement

These failures are intentional hard stops because continuing with corrupted workflow state would be less safe than surfacing the persistence problem directly.

## Common Patterns

- Use JSON when human-readable local state matters most.
- Use SQLite when you want durable local storage with transactional replacement semantics.
- Set `state_file` explicitly instead of relying on the default filename when multiple workflows or tests may run in the same workspace.
- Inspect persisted runs through `snapshot()` rather than directly decoding raw task payloads.
- Combine a persisted state file with `workflow_resume_policy="resume_failed"` when workflows should recover from terminal task failures on a later run.