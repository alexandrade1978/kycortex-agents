import logging
import re
from functools import partial
from typing import AbstractSet, Any, Optional, TypedDict

from kycortex_agents.agents.registry import AgentRegistry, build_default_registry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestration.agent_runtime import build_agent_input_runtime, execute_agent
from kycortex_agents.orchestration.artifacts import ArtifactPersistenceSupport
from kycortex_agents.orchestration.output_helpers import (
    normalize_agent_result,
    unredacted_agent_result,
)
from kycortex_agents.orchestration.validation_runtime import (
    provider_call_metadata,
    sanitize_output_provider_call_metadata,
    validate_code_output_for_task_runtime,
    validate_task_output,
    validate_test_output_for_task_runtime,
)
from kycortex_agents.orchestration.workflow_control import (
    build_code_repair_context_from_test_failure_runtime,
    classify_task_failure,
    configure_repair_attempts_runtime,
    dispatch_task_failure,
    build_repair_context_runtime,
    ensure_workflow_running,
    ensure_budget_decomposition_task_runtime,
    execute_runnable_frontier,
    execute_workflow_runtime,
    execute_workflow_loop,
    execute_runnable_tasks,
    execute_workflow_task,
    failed_task_ids_for_repair,
    finish_workflow_if_no_pending_tasks,
    is_repairable_failure_category,
    plan_repair_task_ids_for_cycle,
    queue_active_cycle_repair_runtime,
    run_active_workflow,
    cancel_workflow,
    emit_workflow_progress,
    execution_agent_name,
    exit_if_workflow_cancelled,
    exit_if_workflow_paused,
    log_event,
    override_task,
    pause_workflow,
    resume_failed_workflow_tasks,
    resume_failed_tasks_with_repair_cycle,
    resume_workflow_tasks,
    replay_workflow,
    resume_workflow,
    skip_task,
    validate_agent_resolution,
    ZERO_BUDGET_FAILURE_CATEGORIES,
)
from kycortex_agents.orchestration.workflow_acceptance import evaluate_workflow_acceptance
from kycortex_agents.types import (
    AgentOutput,
)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


class _WorkflowAcceptanceKwargs(TypedDict):
    workflow_acceptance_policy: str
    zero_budget_failure_categories: AbstractSet[str]
    evaluate_workflow_acceptance: Any


class _WorkflowAcceptanceRuntimeKwargs(_WorkflowAcceptanceKwargs):
    log_event: Any


class _WorkflowControlKwargs(TypedDict):
    exit_if_workflow_cancelled: Any
    exit_if_workflow_paused: Any


class Orchestrator:
    """Public workflow runtime for executing tasks with a configured or custom registry.

    The orchestrator intentionally keeps only class-based runtime orchestration here; deterministic
    helper logic lives in `kycortex_agents.orchestration.*` owner modules.
    """

    def __init__(
        self,
        config: Optional[KYCortexConfig] = None,
        registry: Optional[AgentRegistry] = None,
    ) -> None:
        self.config = config or KYCortexConfig()
        self.registry = registry or build_default_registry(self.config)
        self.logger = logging.getLogger("Orchestrator")

    def pause_workflow(self, project: ProjectState, *, reason: str) -> bool:
        """Pause a workflow so the orchestrator stops dispatching new runnable tasks."""

        return pause_workflow(self.logger, project, reason=reason)

    def resume_workflow(self, project: ProjectState, *, reason: str = "paused_workflow") -> bool:
        """Resume a paused workflow so execution can continue on the next run."""

        return resume_workflow(self.logger, project, reason=reason)

    def cancel_workflow(self, project: ProjectState, *, reason: str = "manual_cancel") -> list[str]:
        """Cancel a workflow through the orchestrator control surface."""

        return cancel_workflow(self.logger, project, reason=reason)

    def skip_task(self, project: ProjectState, task_id: str, *, reason: str) -> bool:
        """Skip a task manually through the orchestrator control surface."""

        return skip_task(self.logger, project, task_id, reason=reason)

    def override_task(self, project: ProjectState, task_id: str, output: str | AgentOutput, *, reason: str) -> bool:
        """Complete a task manually through the orchestrator control surface."""

        return override_task(self.logger, project, task_id, output, reason=reason)

    def replay_workflow(self, project: ProjectState, *, reason: str = "manual_replay") -> list[str]:
        """Reset a workflow so it can be executed again from its initial task set."""

        return replay_workflow(self.logger, project, reason=reason)

    def run_task(self, task: Task, project: ProjectState) -> str:
        """Execute one task through the public orchestrator runtime contract."""
        current_execution_agent_name = execution_agent_name(task)
        log_event(
            self.logger,
            "info",
            "task_started",
            project_name=project.project_name,
            task_id=task.id,
            task_title=task.title,
            assigned_to=current_execution_agent_name,
            attempt=task.attempts + 1,
        )
        agent = self.registry.get(current_execution_agent_name)
        agent_input = build_agent_input_runtime(self, task, project)
        project.start_task(task.id)
        normalized_output: Optional[AgentOutput] = None
        try:
            output = execute_agent(agent, agent_input)
            normalized_output = normalize_agent_result(output)
            normalized_output = unredacted_agent_result(agent, normalized_output)
            normalized_output = sanitize_output_provider_call_metadata(normalized_output)
            sandbox_policy = self.config.execution_sandbox_policy()

            validate_code_output_callback = partial(validate_code_output_for_task_runtime, sandbox_policy)
            validate_test_output_callback = partial(validate_test_output_for_task_runtime, sandbox_policy)

            validate_task_output(
                task,
                agent_input.context,
                normalized_output,
                validate_code_output=validate_code_output_callback,
                validate_test_output=validate_test_output_callback,
            )
            ArtifactPersistenceSupport(self.config.output_dir, sanitize_sub=re.sub).persist_artifacts(normalized_output.artifacts)
            for decision in normalized_output.decisions:
                project.add_decision_record(decision)
            for artifact in normalized_output.artifacts:
                project.add_artifact_record(artifact)
            provider_call = provider_call_metadata(agent, normalized_output)
            project.complete_task(task.id, normalized_output, provider_call=provider_call)
        except Exception as exc:
            failure_category = classify_task_failure(task, exc)
            failure_provider_call = provider_call_metadata(agent, normalized_output)
            project.fail_task(
                task.id,
                exc,
                provider_call=failure_provider_call,
                output=normalized_output,
                error_category=failure_category,
            )
            if project.should_retry_task(task.id):
                log_event(
                    self.logger,
                    "warning",
                    "task_retry_scheduled",
                    project_name=project.project_name,
                    task_id=task.id,
                    task_title=task.title,
                    assigned_to=current_execution_agent_name,
                    attempt=task.attempts,
                    error_type=type(exc).__name__,
                )
            else:
                log_event(
                    self.logger,
                    "error",
                    "task_failed",
                    project_name=project.project_name,
                    task_id=task.id,
                    task_title=task.title,
                    assigned_to=current_execution_agent_name,
                    attempt=task.attempts,
                    error_type=type(exc).__name__,
                    provider=failure_provider_call.get("provider") if failure_provider_call else None,
                    model=failure_provider_call.get("model") if failure_provider_call else None,
                )
            raise
        log_event(
            self.logger,
            "info",
            "task_completed",
            project_name=project.project_name,
            task_id=task.id,
            task_title=task.title,
            assigned_to=current_execution_agent_name,
            attempt=task.attempts,
            provider=provider_call.get("provider") if provider_call else None,
            model=provider_call.get("model") if provider_call else None,
            total_tokens=(provider_call.get("usage") or {}).get("total_tokens") if provider_call else None,
        )
        return normalized_output.raw_content

    def execute_workflow(self, project: ProjectState):
        """Execute the full workflow until completion or an unrecoverable failure."""
        workflow_acceptance_policy = self.config.workflow_acceptance_policy
        workflow_max_repair_cycles = self.config.workflow_max_repair_cycles
        workflow_resume_policy = self.config.workflow_resume_policy
        workflow_failure_policy = self.config.workflow_failure_policy

        workflow_control_kwargs: _WorkflowControlKwargs = {
            "exit_if_workflow_cancelled": partial(exit_if_workflow_cancelled, self.logger),
            "exit_if_workflow_paused": partial(exit_if_workflow_paused, self.logger),
        }
        workflow_log_event = partial(log_event, self.logger)
        workflow_emit_progress = partial(emit_workflow_progress, self.logger)
        workflow_acceptance_kwargs: _WorkflowAcceptanceKwargs = {
            "workflow_acceptance_policy": workflow_acceptance_policy,
            "zero_budget_failure_categories": ZERO_BUDGET_FAILURE_CATEGORIES,
            "evaluate_workflow_acceptance": evaluate_workflow_acceptance,
        }
        workflow_acceptance_runtime_kwargs: _WorkflowAcceptanceRuntimeKwargs = {
            **workflow_acceptance_kwargs,
            "log_event": workflow_log_event,
        }

        configure_repair_attempts_for_cycle = partial(
            configure_repair_attempts_runtime,
            build_code_repair_context_from_test_failure=build_code_repair_context_from_test_failure_runtime,
            ensure_budget_decomposition_task=ensure_budget_decomposition_task_runtime,
            build_repair_context=build_repair_context_runtime,
        )

        queue_active_cycle_repair_for_failure = partial(
            queue_active_cycle_repair_runtime,
            workflow_resume_policy=workflow_resume_policy,
            configure_repair_attempts=configure_repair_attempts_for_cycle,
            ensure_budget_decomposition_task=ensure_budget_decomposition_task_runtime,
            log_event=workflow_log_event,
        )

        dispatch_task_failure_for_workflow = partial(
            dispatch_task_failure,
            workflow_failure_policy=workflow_failure_policy,
            is_repairable_failure=is_repairable_failure_category,
            queue_active_cycle_repair=queue_active_cycle_repair_for_failure,
            emit_workflow_progress=workflow_emit_progress,
            **workflow_acceptance_runtime_kwargs,
        )

        resume_failed_tasks_with_repair_cycle_for_resume = partial(
            resume_failed_tasks_with_repair_cycle,
            configure_repair_attempts=configure_repair_attempts_for_cycle,
            repair_task_ids_for_cycle=partial(
                plan_repair_task_ids_for_cycle,
                ensure_budget_decomposition_task=ensure_budget_decomposition_task_runtime,
            ),
            log_event=workflow_log_event,
        )

        resume_failed_workflow_tasks_for_resume = partial(
            resume_failed_workflow_tasks,
            is_repairable_failure=is_repairable_failure_category,
            **workflow_acceptance_kwargs,
            resume_failed_tasks_with_repair_cycle=resume_failed_tasks_with_repair_cycle_for_resume,
        )

        resume_workflow_tasks_for_execution = partial(
            resume_workflow_tasks,
            workflow_resume_policy=workflow_resume_policy,
            failed_task_ids_for_repair=failed_task_ids_for_repair,
            resume_failed_workflow_tasks=resume_failed_workflow_tasks_for_resume,
            log_event=workflow_log_event,
        )

        ensure_workflow_running_for_active = partial(
            ensure_workflow_running,
            workflow_acceptance_policy=workflow_acceptance_policy,
            workflow_max_repair_cycles=workflow_max_repair_cycles,
            log_event=workflow_log_event,
        )

        finish_workflow_if_no_pending_tasks_for_loop = partial(
            finish_workflow_if_no_pending_tasks,
            **workflow_acceptance_runtime_kwargs,
        )

        execute_workflow_task_for_task = partial(
            execute_workflow_task,
            run_task=self.run_task,
            classify_task_failure=classify_task_failure,
            dispatch_task_failure=dispatch_task_failure_for_workflow,
            emit_workflow_progress=workflow_emit_progress,
            **workflow_control_kwargs,
        )

        execute_runnable_tasks_for_frontier = partial(
            execute_runnable_tasks,
            execute_workflow_task=execute_workflow_task_for_task,
        )

        execute_runnable_frontier_for_loop = partial(
            execute_runnable_frontier,
            execute_runnable_tasks=execute_runnable_tasks_for_frontier,
            **workflow_acceptance_runtime_kwargs,
        )

        execute_workflow_loop_for_active = partial(
            execute_workflow_loop,
            finish_workflow_if_no_pending_tasks=finish_workflow_if_no_pending_tasks_for_loop,
            execute_runnable_frontier=execute_runnable_frontier_for_loop,
            **workflow_control_kwargs,
        )

        run_active_workflow_for_execution = partial(
            run_active_workflow,
            ensure_workflow_running=ensure_workflow_running_for_active,
            execute_workflow_loop=execute_workflow_loop_for_active,
            log_event=workflow_log_event,
            **workflow_control_kwargs,
        )

        execute_workflow_runtime(
            project,
            exit_if_workflow_cancelled=workflow_control_kwargs["exit_if_workflow_cancelled"],
            execution_plan=project.execution_plan,
            validate_agent_resolution=validate_agent_resolution,
            registry=self.registry,
            workflow_max_repair_cycles=workflow_max_repair_cycles,
            resume_workflow_tasks=resume_workflow_tasks_for_execution,
            run_active_workflow=run_active_workflow_for_execution,
        )
