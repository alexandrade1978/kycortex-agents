# Workflow Guide

This guide explains how to define workflows, how dependency-aware scheduling works, and how retry, failure, and resume policies affect execution.

## Workflow Model

Workflows in `kycortex-agents` are represented by a `ProjectState` containing a list of `Task` records.

Each task defines:

- `id`: stable task identifier
- `title`: human-readable task label
- `description`: work request passed to the assigned agent
- `assigned_to`: registry key for the target agent
- `dependencies`: upstream task ids that must complete first
- `retry_limit`: number of retry attempts allowed after failures

The orchestrator uses this task graph to determine runnable work instead of executing tasks in a fixed linear order.

## Defining Tasks

The simplest workflow starts with a `ProjectState` and tasks added through `project.add_task()`.

Example:

```python
from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task

config = KYCortexConfig(llm_model="gpt-4o-mini")

project = ProjectState(
    project_name="SimpleRESTAPI",
    goal="Build a simple FastAPI REST API with 2 endpoints: GET /status and POST /data",
)

project.add_task(Task(
    id="task_1_arch",
    title="Design architecture",
    description="Design module structure for a simple FastAPI project with 2 endpoints.",
    assigned_to="architect",
))

project.add_task(Task(
    id="task_2_code",
    title="Implement code",
    description="Write the FastAPI application code based on architecture.",
    assigned_to="code_engineer",
    dependencies=["task_1_arch"],
))

project.add_task(Task(
    id="task_3_review",
    title="Code review",
    description="Review the FastAPI code for issues.",
    assigned_to="code_reviewer",
    dependencies=["task_2_code"],
))

Orchestrator(config).execute_workflow(project)
```

This mirrors the packaged example in `examples/example_simple_project.py`.

## Dependency Scheduling

The workflow runtime uses explicit dependency ids to decide when a task becomes runnable.

- tasks without dependencies can run first
- tasks with dependencies remain blocked until all upstream tasks are `done`
- unknown dependency ids fail fast during workflow planning
- cyclic dependency graphs fail fast during execution-plan validation

`ProjectState.execution_plan()` and `ProjectState.runnable_tasks()` expose this dependency-aware scheduling model directly.

## Agent Resolution

Before workflow execution starts, the orchestrator validates that every `assigned_to` value can be resolved by the `AgentRegistry`.

This means misconfigured workflows fail before any task starts if an agent key is unknown.

The built-in registry includes the packaged agent roles such as:

- `architect`
- `code_engineer`
- `code_reviewer`
- `qa_tester`
- `docs_writer`
- `legal_advisor`

## Retry Behavior

Tasks can declare `retry_limit` to allow automatic retries after failures.

Runtime behavior:

- when a task fails and still has retry budget left, the task is moved back to `pending`
- the last error is preserved for diagnostics
- the next run increments `attempts`
- workflow execution continues with the pending retriable task instead of marking the workflow terminal immediately

This behavior is useful when provider or validation failures are expected to be transient.

## Output Validation And Repair Context

Generated code and test artifacts are validated before the workflow treats them as successful outputs.

Code validation can enforce:

- Python syntax validity
- task-derived line budgets such as `under 300 lines`
- required CLI entrypoints when the task explicitly asks for a CLI or `__main__` path
- completion diagnostics that combine provider token-limit metadata with structural end-of-file heuristics to detect likely truncated outputs

Test validation can additionally enforce:

- exact or maximum top-level test counts parsed from task text
- fixture-count budgets parsed from task text
- import, call-arity, constructor-arity, payload-contract, and batch-shape checks derived from the generated implementation
- undefined fixture and undefined local-name detection inside generated tests
- safe pytest execution inside the execution sandbox
- completion diagnostics for likely truncated test files

When a failed task is resumed under `workflow_resume_policy="resume_failed"`, the runtime can materialize corrective repair work up to `workflow_max_repair_cycles`. The repair context includes the failing artifact content plus a structured validation summary so the next attempt can address concrete blockers instead of guessing from prompt text alone.

## Failure Policies

Workflow-level failure behavior is controlled by `workflow_failure_policy` in `KYCortexConfig`.

Supported values:

- `fail_fast`: stop the workflow as soon as a task reaches terminal failure
- `continue`: continue independent work while skipping descendants blocked by the failed dependency

When `continue` is active, `ProjectState.skip_dependent_tasks()` marks downstream tasks skipped rather than leaving the workflow in a blocked state.

## Resume Policies

Resume behavior is controlled by `workflow_resume_policy` in `KYCortexConfig`.

Supported values:

- `interrupted_only`: re-queue only tasks that were running when execution stopped
- `resume_failed`: also re-queue failed tasks and dependency-skipped descendants

The orchestrator calls:

- `ProjectState.resume_interrupted_tasks()` for interrupted execution recovery
- `ProjectState.resume_failed_tasks()` when failed-workflow resumption is enabled

This lets persisted states continue without manual JSON or SQLite editing.

## Persistence During Execution

Workflow state is saved repeatedly during orchestration, not only at the end.

The runtime persists state after:

- interrupted-workflow resumption
- task failures
- task completions
- workflow terminal transitions

Artifact files themselves are written under `output_dir` only when a task actually produces persisted content. Configuration no longer creates that directory eagerly during `KYCortexConfig` initialization.

This design ensures retries, failures, artifacts, decisions, provider metadata, and execution events survive restarts.

The terminal `workflow_finished` execution event now carries the public `acceptance_evaluation` summary directly and omits the old embedded `workflow_telemetry` payload. Exact operator-facing workflow telemetry now lives behind `ProjectState.internal_runtime_telemetry()`.

## Context Flow Between Tasks

When a task runs, the orchestrator builds a context payload from:

- project metadata
- filtered `AgentView` snapshot data derived from the current task dependency closure
- completed upstream task outputs keyed by task id
- semantic aliases such as `architecture`, `code`, `review`, `tests`, `documentation`, and `legal`

This means downstream tasks can depend on upstream outputs without needing custom global state wiring.

The broader public `ProjectSnapshot` still exists for inspection and compatibility, but agents do not receive that raw snapshot directly anymore.

Raw completed-task outputs, semantic aliases, and planned-module hints now follow the same dependency-closure rule, so finished tasks outside the active closure do not leak into downstream prompt context.

## Inspecting Workflow State

Useful public inspection methods on `ProjectState` include:

- `pending_tasks()`
- `runnable_tasks()`
- `blocked_tasks()`
- `execution_plan()`
- `task_results()`
- `snapshot()`
- `summary()`

These methods are the preferred way to inspect workflow progress, blocked dependencies, and normalized task results.

`snapshot()` remains the public read model. Exact resume state stays in `ProjectState`, and prompt-facing execution context uses `AgentView` instead of the raw snapshot.

When consumers need workflow-level observability instead of per-task detail, use `ProjectState.internal_runtime_telemetry()` rather than `snapshot()`. The public snapshot intentionally omits `workflow_telemetry`, and per-task public results keep only coarse provider-call and duration presence signals in `TaskResult.details` instead of a separate `resource_telemetry` surface.

## Common Configuration Patterns

Fail-fast execution:

```python
config = KYCortexConfig(
    llm_provider="openai",
    llm_model="gpt-4o-mini",
    workflow_failure_policy="fail_fast",
    workflow_resume_policy="interrupted_only",
)
```

Resume-friendly execution:

```python
config = KYCortexConfig(
    llm_provider="openai",
    llm_model="gpt-4o-mini",
    workflow_failure_policy="continue",
    workflow_resume_policy="resume_failed",
)
```

## Troubleshooting Workflow Failures

When a workflow does not progress as expected, inspect these areas first:

1. invalid or cyclic task dependencies
2. unknown `assigned_to` agent keys
3. provider configuration failures in `KYCortexConfig`
4. tasks exhausted their retry budget and reached terminal failure
5. downstream tasks were intentionally skipped by the `continue` failure policy

The persisted `ProjectState`, execution events, and workflow summary usually provide enough information to diagnose the cause.

## Production Service Objectives

The workflow runtime is acceptance-first: a workflow only counts as successful when its declared acceptance criteria pass end to end.

For production-readiness decisions, treat these as separate questions:

- Did the package release validate and publish correctly?
- Did the workflow runtime stay inside the repository-owned SLO and error-budget policy?
- Did the candidate satisfy the staged canary or go-live gates for the deployment claim being made?

Use `RELEASE.md` for package-release validation.

Use `docs/go-live-policy.md` for the operational SLOs, error budgets, and staged gates that govern canary and production deployment decisions.