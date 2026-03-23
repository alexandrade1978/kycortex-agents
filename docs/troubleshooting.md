# Troubleshooting Guide

This guide covers the most common runtime failures in `kycortex-agents`, how those failures surface through the public API, and how to inspect persisted state when workflows do not complete as expected.

## Failure Surface Overview

Most runtime failures normalize into a small public exception set:

- `ConfigValidationError` for invalid runtime configuration
- `AgentExecutionError` for invalid agent execution, provider failures, blocked workflows, or invalid outputs
- `StatePersistenceError` for save/load failures
- `WorkflowDefinitionError` for invalid workflow graphs such as unknown or cyclic dependencies

These exceptions are meant to fail fast at the public boundary instead of silently producing partial workflow state.

## Configuration Problems

Start with `KYCortexConfig` when a workflow fails before any task runs.

Common configuration failures include:

- unsupported `llm_provider` values
- missing `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
- invalid `workflow_failure_policy` or `workflow_resume_policy`
- invalid `temperature`, `max_tokens`, or `timeout_seconds`
- empty required fields such as `project_name`, `llm_model`, or `output_dir`

If configuration is created successfully but provider-specific credentials are still missing, call `validate_runtime()` to surface the failure immediately.

## Provider And Agent Failures

Provider-backed agent errors surface as `AgentExecutionError`.

Typical causes:

- the provider call failed or timed out
- the backend returned an invalid or empty response
- the agent returned empty text
- the agent returned a value that cannot be normalized into `AgentOutput`
- required context keys were missing for the agent

Built-in agents and custom `BaseAgent` subclasses both flow through the same normalization and validation path.

## Unknown Agents And Invalid Workflows

Two setup mistakes are worth separating:

- unknown task assignments fail through `AgentExecutionError` during orchestrator agent-resolution checks
- invalid dependency graphs fail through `WorkflowDefinitionError`

Examples of invalid workflow definitions include:

- a task depending on an unknown task id
- cyclic dependencies in the task graph

These failures happen before normal execution starts, which prevents partial runs against malformed workflow definitions.

## Blocked Workflows

A workflow can also fail after validation if pending tasks become impossible to schedule.

The usual case is a persisted state where an upstream task is already terminal and a downstream task is still pending with unsatisfied dependencies. In that case the orchestrator raises `AgentExecutionError` with a blocked-workflow message and logs a `workflow_blocked` audit record.

When this happens, inspect:

- pending task ids
- dependency status of each blocked task
- the project `phase`
- the persisted execution events for `workflow_blocked`

## Retries And Resume Behavior

If a task has retry budget remaining, `ProjectState.fail_task()` re-queues it back to `PENDING` instead of marking it terminal.

Relevant controls:

- task-level `retry_limit`
- `workflow_failure_policy="fail_fast"` or `"continue"`
- `workflow_resume_policy="interrupted_only"` or `"resume_failed"`

Use `workflow_resume_policy="resume_failed"` when later reruns should re-queue failed tasks and dependency-skipped descendants from persisted state.

## Persistence Failures

State save/load problems surface as `StatePersistenceError`.

Common causes:

- missing state files
- invalid JSON payloads
- invalid SQLite schema
- malformed persisted SQLite payloads
- filesystem failures during atomic replacement

If persistence is failing repeatedly, simplify the setup first by switching to a local JSON state file and confirming that `ProjectState.save()` and `ProjectState.load()` work in isolation.

## Inspecting Persisted State

When a workflow behaves unexpectedly, inspect the persisted state instead of guessing from logs alone.

The most useful entrypoints are:

- `ProjectState.load(path)` to reload the saved run
- `snapshot()` to build a normalized `ProjectSnapshot`
- `task_results()` to inspect current task-level output and failure details
- `execution_events` to inspect workflow and task audit history
- per-task `history` to inspect retries, resumes, skips, failures, and completions

The snapshot is usually the best read model because it normalizes legacy state and exposes structured `FailureRecord`, `DecisionRecord`, and `ArtifactRecord` values.

## Recovery Patterns

Practical recovery steps depend on the failure class:

1. `ConfigValidationError`: fix configuration or environment variables, then rerun.
2. `WorkflowDefinitionError`: correct dependencies or task assignments before rerunning.
3. `AgentExecutionError` with retry budget left: rerun normally and let the orchestrator retry.
4. `AgentExecutionError` on a terminal failed workflow: rerun from persisted state with `workflow_resume_policy="resume_failed"` when appropriate.
5. `StatePersistenceError`: fix the state-file path or payload integrity before resuming execution.

## Audit Trail Signals

The orchestrator and project state persist structured events that help narrow failures quickly.

Key events include:

- `workflow_started`
- `workflow_resumed`
- `task_retry_scheduled`
- `task_failed`
- `task_skipped`
- `workflow_blocked`
- `dependent_tasks_skipped`
- `workflow_finished`

If the failure mode is unclear, checking these event names in order is usually faster than reading raw task output first.

## Preventive Practices

- validate configuration early, especially provider credentials
- give each workflow an explicit `state_file` path when runs may overlap
- use dependency-aware task definitions instead of relying on implicit ordering
- keep custom agents on the `BaseAgent` contract so input and output validation remains active
- inspect `snapshot()` output during tests to verify retry, skip, and resume behavior before using new workflow patterns in production