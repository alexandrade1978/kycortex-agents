import logging
import re
from typing import AbstractSet, Literal, Optional

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX fallback
    resource = None  # type: ignore[assignment]

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
    validate_code_output_for_task_runtime as _validate_code_output_for_task_runtime,
    validate_task_output,
    validate_test_output_for_task_runtime as _validate_test_output_for_task_runtime,
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
    plan_repair_task_ids_for_cycle,
    queue_active_cycle_repair_runtime as _queue_active_cycle_repair_runtime,
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
)
from kycortex_agents.orchestration.workflow_acceptance import evaluate_workflow_acceptance
from kycortex_agents.types import (
    AgentOutput,
    FailureCategory,
)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


_ZERO_BUDGET_FAILURE_CATEGORIES = frozenset({FailureCategory.SANDBOX_SECURITY_VIOLATION.value})
_REPAIRABLE_FAILURE_CATEGORIES = frozenset(
    {
        FailureCategory.UNKNOWN.value,
        FailureCategory.TASK_EXECUTION.value,
        FailureCategory.CODE_VALIDATION.value,
        FailureCategory.TEST_VALIDATION.value,
        FailureCategory.DEPENDENCY_VALIDATION.value,
        FailureCategory.PROVIDER_TRANSIENT.value,
    }
)


def _is_repairable_failure_category(failure_category: str) -> bool:
    return failure_category in _REPAIRABLE_FAILURE_CATEGORIES


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
            validate_task_output(
                task,
                agent_input.context,
                normalized_output,
                validate_code_output=lambda output, task=None: _validate_code_output_for_task_runtime(
                    sandbox_policy,
                    output,
                    task,
                ),
                validate_test_output=lambda context, output, task=None: _validate_test_output_for_task_runtime(
                    sandbox_policy,
                    context,
                    output,
                    task,
                ),
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

        def workflow_exit_if_cancelled(current_project: ProjectState) -> bool:
            return exit_if_workflow_cancelled(self.logger, current_project)

        def workflow_exit_if_paused(current_project: ProjectState) -> bool:
            return exit_if_workflow_paused(self.logger, current_project)

        def workflow_log_event(level: str, event: str, **fields: object) -> None:
            log_event(self.logger, level, event, **fields)

        def workflow_emit_progress(progress_project: ProjectState, *, task: Task | None = None) -> None:
            emit_workflow_progress(
                self.logger,
                progress_project,
                task=task,
            )

        def configure_repair_attempts_for_cycle(
            current_project: ProjectState,
            failed_task_ids: list[str],
            cycle: dict[str, object],
        ) -> None:
            configure_repair_attempts_runtime(
                current_project,
                failed_task_ids,
                cycle,
                build_code_repair_context_from_test_failure=build_code_repair_context_from_test_failure_runtime,
                ensure_budget_decomposition_task=ensure_budget_decomposition_task_runtime,
                build_repair_context=build_repair_context_runtime,
            )

        def plan_repair_task_ids_for_cycle_for_resume(
            current_project: ProjectState,
            failed_task_ids: list[str],
        ) -> list[str]:
            return plan_repair_task_ids_for_cycle(
                current_project,
                failed_task_ids,
                ensure_budget_decomposition_task=ensure_budget_decomposition_task_runtime,
            )

        def queue_active_cycle_repair_for_failure(
            current_project: ProjectState,
            current_task: Task,
        ) -> bool:
            return _queue_active_cycle_repair_runtime(
                current_project,
                current_task,
                workflow_resume_policy=workflow_resume_policy,
                configure_repair_attempts=configure_repair_attempts_for_cycle,
                ensure_budget_decomposition_task=ensure_budget_decomposition_task_runtime,
                log_event=workflow_log_event,
            )

        def dispatch_task_failure_for_workflow(
            dispatch_project: ProjectState,
            *,
            task: Task,
            failure_category: str,
        ) -> Literal["continue", "raise"]:
            return dispatch_task_failure(
                dispatch_project,
                task=task,
                failure_category=failure_category,
                workflow_failure_policy=workflow_failure_policy,
                workflow_acceptance_policy=workflow_acceptance_policy,
                zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                is_repairable_failure=_is_repairable_failure_category,
                queue_active_cycle_repair=queue_active_cycle_repair_for_failure,
                emit_workflow_progress=workflow_emit_progress,
                evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                log_event=workflow_log_event,
            )

        def resume_failed_tasks_with_repair_cycle_for_resume(
            repair_project: ProjectState,
            resume_failed_task_ids: list[str],
            resume_failure_categories: AbstractSet[str],
            *,
            workflow_acceptance_policy: str,
            zero_budget_failure_categories: AbstractSet[str],
            evaluate_workflow_acceptance,
        ) -> list[str]:
            return resume_failed_tasks_with_repair_cycle(
                repair_project,
                resume_failed_task_ids,
                resume_failure_categories,
                workflow_acceptance_policy=workflow_acceptance_policy,
                zero_budget_failure_categories=zero_budget_failure_categories,
                evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                configure_repair_attempts=configure_repair_attempts_for_cycle,
                repair_task_ids_for_cycle=plan_repair_task_ids_for_cycle_for_resume,
                log_event=workflow_log_event,
            )

        def resume_failed_workflow_tasks_for_resume(
            resume_project: ProjectState,
            current_failed_task_ids: list[str],
            current_failure_categories: AbstractSet[str],
        ) -> list[str]:
            return resume_failed_workflow_tasks(
                resume_project,
                current_failed_task_ids,
                current_failure_categories,
                is_repairable_failure=_is_repairable_failure_category,
                workflow_acceptance_policy=workflow_acceptance_policy,
                zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                resume_failed_tasks_with_repair_cycle=resume_failed_tasks_with_repair_cycle_for_resume,
            )

        def resume_workflow_tasks_for_execution(current_project: ProjectState) -> list[str]:
            return resume_workflow_tasks(
                current_project,
                workflow_resume_policy=workflow_resume_policy,
                failed_task_ids_for_repair=failed_task_ids_for_repair,
                resume_failed_workflow_tasks=resume_failed_workflow_tasks_for_resume,
                log_event=workflow_log_event,
            )

        execute_workflow_runtime(
            project,
            exit_if_workflow_cancelled=workflow_exit_if_cancelled,
            execution_plan=project.execution_plan,
            validate_agent_resolution=validate_agent_resolution,
            registry=self.registry,
            workflow_max_repair_cycles=workflow_max_repair_cycles,
            resume_workflow_tasks=resume_workflow_tasks_for_execution,
            run_active_workflow=lambda current_project: run_active_workflow(
                current_project,
                exit_if_workflow_cancelled=workflow_exit_if_cancelled,
                exit_if_workflow_paused=workflow_exit_if_paused,
                ensure_workflow_running=lambda active_project: ensure_workflow_running(
                    active_project,
                    workflow_acceptance_policy=workflow_acceptance_policy,
                    workflow_max_repair_cycles=workflow_max_repair_cycles,
                    log_event=workflow_log_event,
                ),
                execute_workflow_loop=lambda active_project: execute_workflow_loop(
                    active_project,
                    exit_if_workflow_cancelled=workflow_exit_if_cancelled,
                    exit_if_workflow_paused=workflow_exit_if_paused,
                    pending_tasks=active_project.pending_tasks,
                    finish_workflow_if_no_pending_tasks=lambda loop_project, pending: finish_workflow_if_no_pending_tasks(
                        loop_project,
                        pending,
                        workflow_acceptance_policy=workflow_acceptance_policy,
                        zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                        evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                        log_event=workflow_log_event,
                    ),
                    execute_runnable_frontier=lambda loop_project: execute_runnable_frontier(
                        loop_project,
                        runnable_tasks=loop_project.runnable_tasks,
                        blocked_tasks=loop_project.blocked_tasks,
                        execute_runnable_tasks=lambda runnable_project, current_runnable: execute_runnable_tasks(
                            runnable_project,
                            current_runnable,
                            execute_workflow_task=lambda task_project, *, task: execute_workflow_task(
                                task_project,
                                task=task,
                                run_task=self.run_task,
                                exit_if_workflow_cancelled=workflow_exit_if_cancelled,
                                exit_if_workflow_paused=workflow_exit_if_paused,
                                classify_task_failure=classify_task_failure,
                                dispatch_task_failure=dispatch_task_failure_for_workflow,
                                emit_workflow_progress=workflow_emit_progress,
                            ),
                        ),
                        workflow_acceptance_policy=workflow_acceptance_policy,
                        zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                        evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                        log_event=workflow_log_event,
                    ),
                ),
                log_event=workflow_log_event,
            ),
        )
