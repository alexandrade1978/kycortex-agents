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
- invalid adaptive prompt-policy settings such as unsupported mode names or malformed `provider:model` override keys
- invalid `temperature`, `max_tokens`, `timeout_seconds`, or execution-sandbox limits such as `execution_sandbox_max_wall_clock_seconds`
- empty required fields such as `project_name`, `llm_model`, or `output_dir`

If configuration is created successfully but provider-specific credentials are still missing, call `validate_runtime()` to surface the failure immediately.

An absent `output_dir` on disk immediately after configuration creation is normal. The runtime now creates that directory lazily when artifacts or generated validation files are first written.

Adaptive prompt-policy misconfiguration fails fast through `ConfigValidationError`.

Validate these first when adaptive mode is enabled:

- `adaptive_prompt_default_mode` must be one of `compact`, `balanced`, `rich`
- `adaptive_prompt_compact_threshold_tokens` must be greater than zero
- `adaptive_prompt_mode_overrides` keys must use exact `provider:model` format
- `adaptive_prompt_mode_overrides` values must use supported mode names

If adaptive mode is enabled but generation still appears overly compressed, inspect whether an exact mode override is forcing `compact` for the active provider/model pair.

## Provider And Agent Failures

Provider-backed agent errors surface as `AgentExecutionError`.

Typical causes:

- the provider call failed or timed out
- the backend returned an invalid or empty response
- the backend was reachable but the configured model was not ready for that provider
- the agent returned empty text
- the agent returned a value that cannot be normalized into `AgentOutput`
- required context keys were missing for the agent

Built-in agents and custom `BaseAgent` subclasses both flow through the same normalization and validation path.

Built-in provider health probes now distinguish backend reachability from model readiness. A failed readiness probe with `backend_reachable=True` and `model_ready=False` is deterministic and usually means the configured model name is wrong, unavailable to the current account, or not installed locally in Ollama.

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

## Generated Output Validation Failures

Not every workflow failure comes from a provider outage. The orchestrator also rejects generated artifacts that fail deterministic validation.

Common generated-output failure causes include:

- syntax-invalid or structurally incomplete code or test files
- likely truncated outputs detected from provider token-limit metadata plus end-of-file heuristics
- code tasks that exceeded explicit line budgets or omitted a required CLI entrypoint
- test tasks that exceeded explicit line, fixture, or top-level test-count budgets
- undefined pytest fixtures or undefined local names in generated tests
- payload-contract or batch-shape mismatches between tests and the generated implementation
- artifact paths that would resolve outside `output_dir`, including symlink-based path escapes

When these failures happen, inspect the task's persisted validation metadata or repair summary first. Those summaries now include static validation findings, pytest results when available, and completion diagnostics for likely truncation.

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

If the failure summary mentions likely truncation, reduce task scope, tighten the requested size budget, increase `max_tokens` when justified, or rerun with bounded repair enabled so the corrective task receives the persisted completion diagnostics.

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