import importlib.util
import logging
import os
import re
import subprocess
import sys
from typing import Callable, Dict, Any, Optional

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX fallback
    resource = None  # type: ignore[assignment]

from kycortex_agents.agents.qa_tester import QATesterAgent
from kycortex_agents.agents.registry import AgentRegistry, build_default_registry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import ExecutionSandboxPolicy
from kycortex_agents.orchestration.agent_runtime import build_agent_input_runtime, execute_agent
from kycortex_agents.orchestration.artifacts import ArtifactPersistenceSupport
from kycortex_agents.orchestration.context_building import (
    build_task_context_for_agent_runtime as _build_task_context_for_agent_runtime,
    code_artifact_context_runtime as _code_artifact_context_runtime,
    dependency_artifact_context_runtime as _dependency_artifact_context_runtime,
    planned_module_context_runtime as _planned_module_context_runtime,
    test_artifact_context_runtime as _test_artifact_context_runtime,
)
from kycortex_agents.orchestration.output_helpers import (
    normalize_agent_result,
    summarize_output,
    unredacted_agent_result,
)
from kycortex_agents.orchestration.module_ast_analysis import (
    analyze_python_module,
)
from kycortex_agents.orchestration.sandbox_execution import (
    execute_generated_module_import_runtime as _execute_generated_module_import_runtime,
    execute_generated_tests_runtime as _execute_generated_tests_runtime,
)
from kycortex_agents.orchestration.task_constraints import (
    task_public_contract_preflight,
    task_exact_top_level_test_count,
    task_fixture_budget,
    task_line_budget,
    task_max_top_level_test_count,
    task_requires_cli_entrypoint,
)
from kycortex_agents.orchestration.test_ast_analysis import (
    analyze_test_module_runtime,
    auto_fix_test_type_mismatches,
)
from kycortex_agents.orchestration.validation_reporting import (
    completion_diagnostics_from_provider_call,
    completion_validation_issue,
)
from kycortex_agents.orchestration.validation_runtime import (
    provider_call_metadata,
    redact_validation_execution_result,
    sanitize_output_provider_call_metadata,
    should_validate_code_content as _should_validate_code_content,
    should_validate_test_content as _should_validate_test_content,
    summarize_pytest_output,
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
    active_repair_cycle as _active_repair_cycle,
    has_repair_task_for_cycle as _has_repair_task_for_cycle,
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

active_repair_cycle = _active_repair_cycle
has_repair_task_for_cycle = _has_repair_task_for_cycle
should_validate_code_content = _should_validate_code_content
should_validate_test_content = _should_validate_test_content
build_task_context_for_agent_runtime = _build_task_context_for_agent_runtime
planned_module_context_runtime = _planned_module_context_runtime
code_artifact_context_runtime = _code_artifact_context_runtime
dependency_artifact_context_runtime = _dependency_artifact_context_runtime
test_artifact_context_runtime = _test_artifact_context_runtime


def queue_active_cycle_repair_runtime(
    project: ProjectState,
    task: Task,
    *,
    workflow_resume_policy: str,
    configure_repair_attempts: Callable[[ProjectState, list[str], Dict[str, Any]], None],
    ensure_budget_decomposition_task: Callable[..., Optional[Task]],
    log_event: Callable[..., None],
) -> bool:
    return _queue_active_cycle_repair_runtime(
        project,
        task,
        workflow_resume_policy=workflow_resume_policy,
        configure_repair_attempts=configure_repair_attempts,
        ensure_budget_decomposition_task=ensure_budget_decomposition_task,
        log_event=log_event,
        active_repair_cycle_cb=active_repair_cycle,
        has_repair_task_for_cycle_cb=has_repair_task_for_cycle,
        plan_repair_task_ids_for_cycle_cb=plan_repair_task_ids_for_cycle,
    )

def execute_generated_module_import_runtime(
    sandbox_policy: ExecutionSandboxPolicy,
    module_filename: str,
    code_content: str,
) -> Dict[str, Any]:
    return _execute_generated_module_import_runtime(
        sandbox_policy,
        module_filename,
        code_content,
        python_executable=sys.executable,
        host_env=os.environ,
        subprocess_run=subprocess.run,
        os_module=os,
        resource_module=resource,
        redact_result=redact_validation_execution_result,
    )


def validate_code_output_for_task_runtime(
    sandbox_policy: ExecutionSandboxPolicy,
    output: AgentOutput,
    task: Optional[Task] = None,
) -> None:
    _validate_code_output_for_task_runtime(
        sandbox_policy,
        output,
        task_line_budget(task),
        task_requires_cli_entrypoint(task),
        analyze_python_module=analyze_python_module,
        task_public_contract_preflight=lambda code_analysis: task_public_contract_preflight(task, code_analysis),
        completion_diagnostics_from_provider_call=completion_diagnostics_from_provider_call,
        execute_generated_module_import_runtime=execute_generated_module_import_runtime,
        completion_validation_issue=completion_validation_issue,
    )


def execute_generated_tests_runtime(
    sandbox_policy: ExecutionSandboxPolicy,
    module_filename: str,
    code_content: str,
    test_filename: str,
    test_content: str,
) -> Dict[str, Any]:
    return _execute_generated_tests_runtime(
        sandbox_policy,
        module_filename,
        code_content,
        test_filename,
        test_content,
        python_executable=sys.executable,
        host_env=os.environ,
        pytest_spec_finder=importlib.util.find_spec,
        subprocess_run=subprocess.run,
        os_module=os,
        resource_module=resource,
        summarize_output=summarize_pytest_output,
        redact_result=redact_validation_execution_result,
    )
def validate_test_output_for_task_runtime(
    sandbox_policy: ExecutionSandboxPolicy,
    context: Dict[str, Any],
    output: AgentOutput,
    task: Optional[Task] = None,
) -> None:
    _validate_test_output_for_task_runtime(
        sandbox_policy,
        context,
        output,
        task_line_budget(task),
        task_exact_top_level_test_count(task),
        task_max_top_level_test_count(task),
        task_fixture_budget(task),
        finalize_generated_test_suite=QATesterAgent._finalize_generated_test_suite,
        analyze_test_module_runtime=analyze_test_module_runtime,
        auto_fix_test_type_mismatches=auto_fix_test_type_mismatches,
        execute_generated_tests_runtime=execute_generated_tests_runtime,
        completion_diagnostics_from_provider_call=completion_diagnostics_from_provider_call,
        completion_validation_issue=completion_validation_issue,
        summarize_output=summarize_output,
    )


class Orchestrator:
    """Public workflow runtime for executing tasks with a configured or custom registry.

    Pass a custom AgentRegistry when consumers need to register their own agent
    implementations while keeping `execute_workflow()` and `run_task()` as the
    supported execution entry points.
    """

    def __init__(self, config: Optional[KYCortexConfig] = None, registry: Optional[AgentRegistry] = None):
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
            validate_task_output(
                task,
                agent_input.context,
                normalized_output,
                validate_code_output=lambda output, task=None: validate_code_output_for_task_runtime(
                    self.config.execution_sandbox_policy(),
                    output,
                    task,
                ),
                validate_test_output=lambda context, output, task=None: validate_test_output_for_task_runtime(
                    self.config.execution_sandbox_policy(),
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
            project.fail_task(
                task.id,
                exc,
                provider_call=provider_call_metadata(agent, normalized_output),
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
                provider_call = provider_call_metadata(agent, normalized_output)
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
                    provider=provider_call.get("provider") if provider_call else None,
                    model=provider_call.get("model") if provider_call else None,
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
        execute_workflow_runtime(
            project,
            exit_if_workflow_cancelled=lambda current_project: exit_if_workflow_cancelled(self.logger, current_project),
            execution_plan=project.execution_plan,
            validate_agent_resolution=validate_agent_resolution,
            registry=self.registry,
            workflow_max_repair_cycles=self.config.workflow_max_repair_cycles,
            resume_workflow_tasks=lambda current_project: resume_workflow_tasks(
                current_project,
                workflow_resume_policy=self.config.workflow_resume_policy,
                failed_task_ids_for_repair=failed_task_ids_for_repair,
                resume_failed_workflow_tasks=lambda resume_project, current_failed_task_ids, current_failure_categories: resume_failed_workflow_tasks(
                    resume_project,
                    current_failed_task_ids,
                    current_failure_categories,
                    is_repairable_failure=lambda failure_category: failure_category in {
                        FailureCategory.UNKNOWN.value,
                        FailureCategory.TASK_EXECUTION.value,
                        FailureCategory.CODE_VALIDATION.value,
                        FailureCategory.TEST_VALIDATION.value,
                        FailureCategory.DEPENDENCY_VALIDATION.value,
                        FailureCategory.PROVIDER_TRANSIENT.value,
                    },
                    workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                    zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                    evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                    resume_failed_tasks_with_repair_cycle=lambda repair_project, resume_failed_task_ids, resume_failure_categories, **kwargs: resume_failed_tasks_with_repair_cycle(
                        repair_project,
                        resume_failed_task_ids,
                        resume_failure_categories,
                        configure_repair_attempts=lambda current_project, failed_task_ids, cycle: configure_repair_attempts_runtime(
                            current_project,
                            failed_task_ids,
                            cycle,
                            build_code_repair_context_from_test_failure=build_code_repair_context_from_test_failure_runtime,
                            ensure_budget_decomposition_task=ensure_budget_decomposition_task_runtime,
                            build_repair_context=build_repair_context_runtime,
                        ),
                        repair_task_ids_for_cycle=lambda current_project, failed_task_ids: plan_repair_task_ids_for_cycle(
                            current_project,
                            failed_task_ids,
                            ensure_budget_decomposition_task=ensure_budget_decomposition_task_runtime,
                        ),
                        log_event=lambda level, event, **fields: log_event(self.logger, level, event, **fields),
                        **kwargs,
                    ),
                ),
                log_event=lambda level, event, **fields: log_event(self.logger, level, event, **fields),
            ),
            run_active_workflow=lambda current_project: run_active_workflow(
                current_project,
                exit_if_workflow_cancelled=lambda active_project: exit_if_workflow_cancelled(self.logger, active_project),
                exit_if_workflow_paused=lambda active_project: exit_if_workflow_paused(self.logger, active_project),
                ensure_workflow_running=lambda active_project: ensure_workflow_running(
                    active_project,
                    workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                    workflow_max_repair_cycles=self.config.workflow_max_repair_cycles,
                    log_event=lambda level, event, **fields: log_event(self.logger, level, event, **fields),
                ),
                execute_workflow_loop=lambda active_project: execute_workflow_loop(
                    active_project,
                    exit_if_workflow_cancelled=lambda loop_project: exit_if_workflow_cancelled(self.logger, loop_project),
                    exit_if_workflow_paused=lambda loop_project: exit_if_workflow_paused(self.logger, loop_project),
                    pending_tasks=active_project.pending_tasks,
                    finish_workflow_if_no_pending_tasks=lambda loop_project, pending: finish_workflow_if_no_pending_tasks(
                        loop_project,
                        pending,
                        workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                        zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                        evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                        log_event=lambda level, event, **fields: log_event(self.logger, level, event, **fields),
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
                                exit_if_workflow_cancelled=lambda current_task_project: exit_if_workflow_cancelled(self.logger, current_task_project),
                                exit_if_workflow_paused=lambda current_task_project: exit_if_workflow_paused(self.logger, current_task_project),
                                classify_task_failure=classify_task_failure,
                                dispatch_task_failure=lambda dispatch_project, *, task, failure_category: dispatch_task_failure(
                                    dispatch_project,
                                    task=task,
                                    failure_category=failure_category,
                                    workflow_failure_policy=self.config.workflow_failure_policy,
                                    workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                                    zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                                    is_repairable_failure=lambda current_failure_category: current_failure_category in {
                                        FailureCategory.UNKNOWN.value,
                                        FailureCategory.TASK_EXECUTION.value,
                                        FailureCategory.CODE_VALIDATION.value,
                                        FailureCategory.TEST_VALIDATION.value,
                                        FailureCategory.DEPENDENCY_VALIDATION.value,
                                        FailureCategory.PROVIDER_TRANSIENT.value,
                                    },
                                    queue_active_cycle_repair=lambda current_project, current_task: queue_active_cycle_repair_runtime(
                                        current_project,
                                        current_task,
                                        workflow_resume_policy=self.config.workflow_resume_policy,
                                        configure_repair_attempts=lambda repair_project, failed_task_ids, cycle: configure_repair_attempts_runtime(
                                            repair_project,
                                            failed_task_ids,
                                            cycle,
                                            build_code_repair_context_from_test_failure=build_code_repair_context_from_test_failure_runtime,
                                            ensure_budget_decomposition_task=ensure_budget_decomposition_task_runtime,
                                            build_repair_context=build_repair_context_runtime,
                                        ),
                                        ensure_budget_decomposition_task=ensure_budget_decomposition_task_runtime,
                                        log_event=lambda level, event, **fields: log_event(self.logger, level, event, **fields),
                                    ),
                                    emit_workflow_progress=lambda progress_project, *, task=None: emit_workflow_progress(
                                        self.logger,
                                        progress_project,
                                        task=task,
                                    ),
                                    evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                                    log_event=lambda level, event, **fields: log_event(self.logger, level, event, **fields),
                                ),
                                emit_workflow_progress=lambda progress_project, *, task=None: emit_workflow_progress(
                                    self.logger,
                                    progress_project,
                                    task=task,
                                ),
                            ),
                        ),
                        workflow_acceptance_policy=self.config.workflow_acceptance_policy,
                        zero_budget_failure_categories=_ZERO_BUDGET_FAILURE_CATEGORIES,
                        evaluate_workflow_acceptance=evaluate_workflow_acceptance,
                        log_event=lambda level, event, **fields: log_event(self.logger, level, event, **fields),
                    ),
                ),
                log_event=lambda level, event, **fields: log_event(self.logger, level, event, **fields),
            ),
        )
