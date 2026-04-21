"""Workflow-control helpers used by the Orchestrator facade."""

from __future__ import annotations

from typing import AbstractSet, Any, Callable, Literal, Optional, cast

from kycortex_agents.exceptions import AgentExecutionError, ProviderTransientError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.orchestration.artifacts import failed_artifact_content
from kycortex_agents.providers.base import redact_sensitive_data
from kycortex_agents.orchestration.output_helpers import validation_payload
from kycortex_agents.orchestration.repair_analysis import (
    dataclass_default_order_repair_examples,
    failed_artifact_content_for_category,
    internal_constructor_strictness_details,
    invalid_outcome_missing_audit_trail_details,
    missing_import_nameerror_details,
    plain_class_field_default_factory_details,
)
from kycortex_agents.orchestration.repair_instructions import (
    build_code_repair_instruction_from_test_failure_runtime,
    build_repair_instruction_runtime,
    repair_owner_for_category,
)
from kycortex_agents.orchestration.repair_analysis import (
    duplicate_constructor_argument_call_hint,
    duplicate_constructor_argument_details,
    duplicate_constructor_explicit_rewrite_hint,
    missing_object_attribute_details,
    nested_payload_wrapper_field_validation_details,
    render_name_list,
    suggest_declared_attribute_replacement,
)
from kycortex_agents.orchestration.repair_test_analysis import (
    failed_test_requires_code_repair_runtime,
    helper_surface_usages_for_test_repair_runtime,
    imported_code_task_for_failed_test,
    normalized_helper_surface_symbols,
    upstream_code_task_for_test_failure,
)
from kycortex_agents.orchestration.ast_tools import python_import_roots
from kycortex_agents.orchestration.context_building import default_module_name_for_task
from kycortex_agents.orchestration.sandbox_execution import sandbox_security_violation
from kycortex_agents.orchestration.task_constraints import (
    build_budget_decomposition_task_context,
    repair_requires_budget_decomposition,
)
from kycortex_agents.orchestration.validation_analysis import (
    pytest_contract_overreach_signals,
    pytest_failure_is_semantic_assertion_mismatch,
    pytest_failure_origin,
    validation_has_blocking_issues,
    validation_has_only_warnings,
)
from kycortex_agents.orchestration.validation_reporting import build_repair_validation_summary
from kycortex_agents.types import AgentOutput, ArtifactType as AgentOutputArtifactType, FailureCategory, TaskStatus, WorkflowOutcome


def log_event(logger: Any, level: str, event: str, **fields: Any) -> None:
    log_method = getattr(logger, level)
    safe_fields = cast(dict[str, Any], redact_sensitive_data(privacy_safe_log_fields(fields)))
    log_method(event, extra={"event": event, **safe_fields})


def privacy_safe_log_fields(fields: dict[str, Any]) -> dict[str, Any]:
    safe_fields: dict[str, Any] = {}
    for field_name, value in fields.items():
        minimized_field_name = task_id_count_log_field_name(field_name)
        if minimized_field_name is not None:
            count = task_id_collection_count(value)
            if count is not None:
                safe_fields[minimized_field_name] = count
                continue
        safe_fields[field_name] = value
    return safe_fields


def task_id_collection_count(value: Any) -> Optional[int]:
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if isinstance(value, str):
        return 1 if value else 0
    if value is None:
        return 0
    return None


def task_id_count_log_field_name(field_name: str) -> Optional[str]:
    if field_name == "task_ids" or field_name.endswith("_task_ids"):
        return f"{field_name[:-len('_ids')]}_count"
    return None


def execution_agent_name(task: Task) -> str:
    repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
    repair_owner = repair_context.get("repair_owner")
    if isinstance(repair_owner, str) and repair_owner.strip():
        return repair_owner
    return task.assigned_to


def classify_task_failure(task: Task, exc: Exception) -> str:
    normalized_role = (task.assigned_to or "").strip().lower()
    if isinstance(exc, WorkflowDefinitionError):
        return FailureCategory.WORKFLOW_DEFINITION.value
    if isinstance(exc, ProviderTransientError):
        return FailureCategory.PROVIDER_TRANSIENT.value
    if sandbox_security_violation(exc):
        return FailureCategory.SANDBOX_SECURITY_VIOLATION.value
    if isinstance(exc, AgentExecutionError):
        if normalized_role == "code_engineer":
            return FailureCategory.CODE_VALIDATION.value
        if normalized_role == "qa_tester":
            return FailureCategory.TEST_VALIDATION.value
        if normalized_role == "dependency_manager":
            return FailureCategory.DEPENDENCY_VALIDATION.value
    return FailureCategory.TASK_EXECUTION.value


def emit_workflow_progress(logger: Any, project: ProjectState, *, task: Optional[Task] = None) -> None:
    workflow_telemetry = project.record_workflow_progress(
        task_id=task.id if task is not None else None,
        task_status=task.status if task is not None else None,
    )
    log_event(
        logger,
        "info",
        "workflow_progress",
        project_name=project.project_name,
        phase=project.phase,
        task_id=task.id if task is not None else None,
        task_status=task.status if task is not None else None,
        workflow_telemetry=workflow_telemetry,
    )


def pause_workflow(logger: Any, project: ProjectState, *, reason: str) -> bool:
    changed = project.pause_workflow(reason=reason)
    if changed:
        project.save()
        log_event(
            logger,
            "info",
            "workflow_paused",
            project_name=project.project_name,
            phase=project.phase,
            reason=project.workflow_pause_reason,
        )
    return changed


def resume_workflow(logger: Any, project: ProjectState, *, reason: str = "paused_workflow") -> bool:
    changed = project.resume_workflow(reason=reason)
    if changed:
        project.save()
        log_event(
            logger,
            "info",
            "workflow_resumed",
            project_name=project.project_name,
            phase=project.phase,
            reason=reason,
        )
    return changed


def cancel_workflow(logger: Any, project: ProjectState, *, reason: str = "manual_cancel") -> list[str]:
    was_cancelled = project.is_workflow_cancelled()
    cancelled_task_ids = project.cancel_workflow(reason=reason)
    if not was_cancelled and project.is_workflow_cancelled():
        project.save()
        log_event(
            logger,
            "warning",
            "workflow_cancelled",
            project_name=project.project_name,
            phase=project.phase,
            reason=reason,
            cancelled_task_ids=list(cancelled_task_ids),
        )
    return cancelled_task_ids


def skip_task(logger: Any, project: ProjectState, task_id: str, *, reason: str) -> bool:
    task = project.get_task(task_id)
    if task is None:
        return False
    project.skip_task(task_id, reason, reason_type="manual")
    project.save()
    log_event(
        logger,
        "info",
        "task_skipped",
        project_name=project.project_name,
        task_id=task_id,
        phase=project.phase,
        reason=reason,
    )
    return True


def override_task(
    logger: Any,
    project: ProjectState,
    task_id: str,
    output: str | AgentOutput,
    *,
    reason: str,
) -> bool:
    changed = project.override_task(task_id, output, reason=reason)
    if changed:
        project.save()
        log_event(
            logger,
            "info",
            "task_overridden",
            project_name=project.project_name,
            task_id=task_id,
            phase=project.phase,
            reason=reason,
        )
    return changed


def replay_workflow(logger: Any, project: ProjectState, *, reason: str = "manual_replay") -> list[str]:
    replayed_task_ids = project.replay_workflow(reason=reason)
    if replayed_task_ids:
        project.save()
        log_event(
            logger,
            "info",
            "workflow_replayed",
            project_name=project.project_name,
            phase=project.phase,
            reason=reason,
            replayed_task_ids=list(replayed_task_ids),
        )
    return replayed_task_ids


def ensure_budget_decomposition_task(
    project: ProjectState,
    task: Task,
    repair_context: dict[str, Any],
    *,
    requires_budget_decomposition: Callable[[dict[str, Any]], bool],
    build_budget_decomposition_task_context: Callable[[Task, dict[str, Any]], dict[str, Any]],
) -> Optional[Task]:
    decomposition_task_id = repair_context.get("budget_decomposition_plan_task_id")
    if isinstance(decomposition_task_id, str) and decomposition_task_id.strip():
        existing = project.get_task(decomposition_task_id)
        if existing is not None:
            return existing
    if not requires_budget_decomposition(repair_context):
        return None
    decomposition_task = project._create_budget_decomposition_task(
        task.id,
        build_budget_decomposition_task_context(task, repair_context),
    )
    if decomposition_task is not None:
        repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
    return decomposition_task


def ensure_budget_decomposition_task_runtime(
    project: ProjectState,
    task: Task,
    repair_context: dict[str, Any],
) -> Optional[Task]:
    return ensure_budget_decomposition_task(
        project,
        task,
        repair_context,
        requires_budget_decomposition=repair_requires_budget_decomposition,
        build_budget_decomposition_task_context=lambda current_task, current_repair_context: build_budget_decomposition_task_context(
            current_task,
            current_repair_context,
            execution_agent_name(current_task),
        ),
    )


def active_repair_cycle(project: ProjectState) -> dict[str, Any] | None:
    if not project.repair_history:
        return None
    current_cycle = project.repair_history[-1]
    if not isinstance(current_cycle, dict):
        return None
    return current_cycle


def has_repair_task_for_cycle(project: ProjectState, task_id: str, cycle_number: int) -> bool:
    for existing_task in project.tasks:
        if existing_task.repair_origin_task_id != task_id:
            continue
        if existing_task.repair_attempt != cycle_number:
            continue
        return True
    return False


def failed_task_ids_for_repair(project: ProjectState) -> list[str]:
    active_repair_origins = {
        task.repair_origin_task_id
        for task in project.tasks
        if task.repair_origin_task_id
        and task.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}
    }
    return [
        task.id
        for task in project.tasks
        if task.status == TaskStatus.FAILED.value
        and not task.repair_origin_task_id
        and task.id not in active_repair_origins
    ]


def repair_task_ids_for_cycle(
    project: ProjectState,
    failed_task_ids: list[str],
    *,
    test_failure_requires_code_repair,
    upstream_code_task_for_test_failure,
    ensure_budget_decomposition_task,
    execution_agent_name,
) -> list[str]:
    repair_task_ids: list[str] = []
    for task_id in failed_task_ids:
        task = project.get_task(task_id)
        if task is None:
            continue

        code_repair_task: Task | None = None
        if test_failure_requires_code_repair(task):
            code_task = upstream_code_task_for_test_failure(project, task)
            if code_task is not None:
                code_repair_context = code_task.repair_context if isinstance(code_task.repair_context, dict) else {}
                code_decomposition_task = ensure_budget_decomposition_task(project, code_task, code_repair_context)
                if code_decomposition_task is not None and code_decomposition_task.id not in repair_task_ids:
                    repair_task_ids.append(code_decomposition_task.id)
                code_repair_owner = execution_agent_name(code_task)
                code_repair_task = project._create_repair_task(code_task.id, code_repair_owner, code_repair_context)
                if code_repair_task is not None:
                    if code_repair_task.id not in task.dependencies:
                        task.dependencies.append(code_repair_task.id)
                    if code_decomposition_task is not None:
                        if code_decomposition_task.id not in code_repair_task.dependencies:
                            code_repair_task.dependencies.append(code_decomposition_task.id)
                        if isinstance(code_repair_task.repair_context, dict):
                            code_repair_task.repair_context["budget_decomposition_plan_task_id"] = code_decomposition_task.id
                    if code_repair_task.id not in repair_task_ids:
                        repair_task_ids.append(code_repair_task.id)

        repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
        decomposition_task = ensure_budget_decomposition_task(project, task, repair_context)
        if decomposition_task is not None and decomposition_task.id not in repair_task_ids:
            repair_task_ids.append(decomposition_task.id)
        repair_owner = execution_agent_name(task)
        repair_task = project._create_repair_task(task_id, repair_owner, repair_context)
        if repair_task is not None:
            if decomposition_task is not None:
                if decomposition_task.id not in repair_task.dependencies:
                    repair_task.dependencies.append(decomposition_task.id)
                if isinstance(repair_task.repair_context, dict):
                    repair_task.repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
            if code_repair_task is not None and code_repair_task.id not in repair_task.dependencies:
                repair_task.dependencies.append(code_repair_task.id)
            repair_task_ids.append(repair_task.id)
    return repair_task_ids


def plan_repair_task_ids_for_cycle(
    project: ProjectState,
    failed_task_ids: list[str],
    *,
    ensure_budget_decomposition_task: Callable[..., Optional[Task]],
) -> list[str]:
    return repair_task_ids_for_cycle(
        project,
        failed_task_ids,
        test_failure_requires_code_repair=lambda task: failed_test_requires_code_repair_runtime(
            task,
            validation_payload=validation_payload,
            pytest_failure_origin=pytest_failure_origin,
            pytest_contract_overreach_signals=pytest_contract_overreach_signals,
            test_validation_has_blocking_issues=validation_has_blocking_issues,
            pytest_failure_is_semantic_assertion_mismatch=pytest_failure_is_semantic_assertion_mismatch,
        ),
        upstream_code_task_for_test_failure=lambda current_project, current_task: upstream_code_task_for_test_failure(
            current_project,
            current_task,
            imported_code_task_for_failed_test=lambda imported_project, imported_task: imported_code_task_for_failed_test(
                imported_project,
                imported_task,
                failed_artifact_content=lambda artifact_task, artifact_type=None: failed_artifact_content(
                    artifact_task.output,
                    artifact_task.output_payload,
                    artifact_type,
                ),
                python_import_roots=python_import_roots,
                default_module_name_for_task=default_module_name_for_task,
            ),
        ),
        ensure_budget_decomposition_task=ensure_budget_decomposition_task,
        execution_agent_name=execution_agent_name,
    )


def configure_repair_attempts(
    project: ProjectState,
    failed_task_ids: list[str],
    cycle: dict[str, Any],
    *,
    test_failure_requires_code_repair,
    upstream_code_task_for_test_failure,
    build_code_repair_context_from_test_failure,
    ensure_budget_decomposition_task,
    build_repair_context,
) -> None:
    planned_task_ids: set[str] = set()
    for failed_task_id in failed_task_ids:
        task = project.get_task(failed_task_id)
        if task is None:
            continue

        if test_failure_requires_code_repair(task):
            code_task = upstream_code_task_for_test_failure(project, task)
            if code_task is not None and code_task.id not in planned_task_ids:
                code_repair_context = build_code_repair_context_from_test_failure(code_task, task, cycle)
                decomposition_task = ensure_budget_decomposition_task(project, code_task, code_repair_context)
                if decomposition_task is not None:
                    code_repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
                project._plan_task_repair(code_task.id, code_repair_context)
                planned_task_ids.add(code_task.id)

        if task.id in planned_task_ids:
            continue

        repair_context = build_repair_context(task, cycle)
        decomposition_task = ensure_budget_decomposition_task(project, task, repair_context)
        if decomposition_task is not None:
            repair_context["budget_decomposition_plan_task_id"] = decomposition_task.id
        project._plan_task_repair(task.id, repair_context)
        planned_task_ids.add(task.id)


def queue_active_cycle_repair(
    project: ProjectState,
    task: Task,
    *,
    workflow_resume_policy: str,
    active_repair_cycle,
    has_repair_task_for_cycle,
    configure_repair_attempts,
    repair_task_ids_for_cycle,
    log_event,
) -> bool:
    if workflow_resume_policy != "resume_failed":
        return False
    if task.repair_origin_task_id is not None:
        return False

    current_cycle = active_repair_cycle(project)
    if current_cycle is None:
        return False
    cycle_number = int(current_cycle.get("cycle") or 0)
    if cycle_number <= 0:
        return False
    if has_repair_task_for_cycle(project, task.id, cycle_number):
        return False

    configure_repair_attempts(project, [task.id], current_cycle)
    repair_task_ids = repair_task_ids_for_cycle(project, [task.id])
    if not repair_task_ids:
        return False

    project.resume_failed_tasks(
        include_failed_tasks=False,
        failed_task_ids=[task.id],
        additional_task_ids=repair_task_ids,
    )
    project._record_execution_event(
        event="task_repair_chained",
        task_id=task.id,
        status=task.status,
        details={
            "repair_task_ids": repair_task_ids,
            "repair_cycle_count": project.repair_cycle_count,
        },
    )
    log_event(
        "info",
        "task_repair_chained",
        project_name=project.project_name,
        task_id=task.id,
        repair_task_ids=repair_task_ids,
        repair_cycle_count=project.repair_cycle_count,
    )
    return True


def queue_active_cycle_repair_runtime(
    project: ProjectState,
    task: Task,
    *,
    workflow_resume_policy: str,
    configure_repair_attempts: Callable[[ProjectState, list[str], dict[str, Any]], None],
    ensure_budget_decomposition_task: Callable[..., Optional[Task]],
    log_event: Callable[..., None],
    active_repair_cycle_cb: Callable[[ProjectState], dict[str, Any] | None] = active_repair_cycle,
    has_repair_task_for_cycle_cb: Callable[[ProjectState, str, int], bool] = has_repair_task_for_cycle,
    plan_repair_task_ids_for_cycle_cb: Callable[..., list[str]] = plan_repair_task_ids_for_cycle,
) -> bool:
    return queue_active_cycle_repair(
        project,
        task,
        workflow_resume_policy=workflow_resume_policy,
        active_repair_cycle=active_repair_cycle_cb,
        has_repair_task_for_cycle=has_repair_task_for_cycle_cb,
        configure_repair_attempts=configure_repair_attempts,
        repair_task_ids_for_cycle=lambda current_project, failed_task_ids: plan_repair_task_ids_for_cycle_cb(
            current_project,
            failed_task_ids,
            ensure_budget_decomposition_task=ensure_budget_decomposition_task,
        ),
        log_event=log_event,
    )


def resume_failed_tasks_with_repair_cycle(
    project: ProjectState,
    failed_task_ids: list[str],
    failure_categories: AbstractSet[str],
    *,
    workflow_acceptance_policy: str,
    zero_budget_failure_categories: AbstractSet[str],
    evaluate_workflow_acceptance,
    configure_repair_attempts,
    repair_task_ids_for_cycle,
    log_event,
) -> list[str]:
    if not project.can_start_repair_cycle():
        acceptance_evaluation = evaluate_workflow_acceptance(
            project,
            workflow_acceptance_policy,
            zero_budget_failure_categories,
        )
        project.mark_workflow_finished(
            "failed",
            acceptance_policy=workflow_acceptance_policy,
            terminal_outcome=WorkflowOutcome.FAILED.value,
            failure_category=FailureCategory.REPAIR_BUDGET_EXHAUSTED.value,
            acceptance_criteria_met=False,
            acceptance_evaluation=acceptance_evaluation,
        )
        project.save()
        log_event(
            "error",
            "workflow_repair_budget_exhausted",
            project_name=project.project_name,
            failed_task_ids=list(failed_task_ids),
            repair_cycle_count=project.repair_cycle_count,
            repair_max_cycles=project.repair_max_cycles,
        )
        raise AgentExecutionError(
            "Workflow repair budget exhausted before resuming failed tasks"
        )

    project.start_repair_cycle(
        reason="resume_failed_tasks",
        failure_category=(
            next(iter(failure_categories)) if len(failure_categories) == 1 else FailureCategory.UNKNOWN.value
        ),
        failed_task_ids=failed_task_ids,
    )
    current_cycle = project.repair_history[-1]
    configure_repair_attempts(project, failed_task_ids, current_cycle)
    repair_task_ids = repair_task_ids_for_cycle(project, failed_task_ids)
    resumed_task_ids = list(repair_task_ids)
    resumed_task_ids.extend(
        project.resume_failed_tasks(
            include_failed_tasks=False,
            failed_task_ids=failed_task_ids,
            additional_task_ids=repair_task_ids,
        )
    )
    return resumed_task_ids


def resume_failed_workflow_tasks(
    project: ProjectState,
    failed_task_ids: list[str],
    failure_categories: AbstractSet[str],
    *,
    is_repairable_failure,
    workflow_acceptance_policy: str,
    zero_budget_failure_categories: AbstractSet[str],
    evaluate_workflow_acceptance,
    resume_failed_tasks_with_repair_cycle,
) -> list[str]:
    non_repairable_categories = {
        category for category in failure_categories if not is_repairable_failure(category)
    }
    if non_repairable_categories:
        resolved_category = (
            next(iter(non_repairable_categories))
            if len(non_repairable_categories) == 1
            else FailureCategory.UNKNOWN.value
        )
        acceptance_evaluation = evaluate_workflow_acceptance(
            project,
            workflow_acceptance_policy,
            zero_budget_failure_categories,
        )
        project.mark_workflow_finished(
            "failed",
            acceptance_policy=workflow_acceptance_policy,
            terminal_outcome=WorkflowOutcome.FAILED.value,
            failure_category=resolved_category,
            acceptance_criteria_met=False,
            acceptance_evaluation=acceptance_evaluation,
        )
        project.save()
        raise AgentExecutionError(
            "Workflow contains non-repairable failed tasks and cannot resume automatically"
        )

    return resume_failed_tasks_with_repair_cycle(
        project,
        failed_task_ids,
        failure_categories,
        workflow_acceptance_policy=workflow_acceptance_policy,
        zero_budget_failure_categories=zero_budget_failure_categories,
        evaluate_workflow_acceptance=evaluate_workflow_acceptance,
    )


def resume_workflow_tasks(
    project: ProjectState,
    *,
    workflow_resume_policy: str,
    failed_task_ids_for_repair,
    resume_failed_workflow_tasks,
    log_event,
) -> list[str]:
    resumed_task_ids = project.resume_interrupted_tasks()
    failed_task_ids = failed_task_ids_for_repair(project)
    if workflow_resume_policy == "resume_failed" and failed_task_ids:
        failure_categories = {
            task.last_error_category or FailureCategory.UNKNOWN.value
            for task in project.tasks
            if task.id in failed_task_ids
        }
        resumed_task_ids.extend(
            resume_failed_workflow_tasks(project, list(failed_task_ids), failure_categories)
        )
    if resumed_task_ids:
        log_event("info", "workflow_resumed", project_name=project.project_name, task_ids=list(resumed_task_ids))
        project.save()
    return resumed_task_ids


def ensure_workflow_running(
    project: ProjectState,
    *,
    workflow_acceptance_policy: str,
    workflow_max_repair_cycles: int,
    log_event,
) -> bool:
    if project.workflow_started_at is not None and project.phase == "execution":
        return False
    project.mark_workflow_running(
        acceptance_policy=workflow_acceptance_policy,
        repair_max_cycles=workflow_max_repair_cycles,
    )
    log_event("info", "workflow_started", project_name=project.project_name, phase=project.phase)
    return True


def finish_workflow_if_no_pending_tasks(
    project: ProjectState,
    pending_tasks: list[Task],
    *,
    workflow_acceptance_policy: str,
    zero_budget_failure_categories: AbstractSet[str],
    evaluate_workflow_acceptance,
    log_event,
) -> bool:
    if pending_tasks:
        return False
    acceptance_evaluation = evaluate_workflow_acceptance(
        project,
        workflow_acceptance_policy,
        zero_budget_failure_categories,
    )
    acceptance_criteria_met = bool(acceptance_evaluation["accepted"])
    project.mark_workflow_finished(
        "completed",
        acceptance_policy=workflow_acceptance_policy,
        terminal_outcome=(
            WorkflowOutcome.COMPLETED.value
            if acceptance_criteria_met
            else WorkflowOutcome.DEGRADED.value
        ),
        acceptance_criteria_met=acceptance_criteria_met,
        acceptance_evaluation=acceptance_evaluation,
    )
    project.save()
    log_event("info", "workflow_completed", project_name=project.project_name, phase=project.phase)
    return True


def fail_workflow_for_definition_error(
    project: ProjectState,
    *,
    workflow_acceptance_policy: str,
    zero_budget_failure_categories: AbstractSet[str],
    evaluate_workflow_acceptance,
    log_event,
) -> None:
    project.mark_workflow_finished(
        "failed",
        acceptance_policy=workflow_acceptance_policy,
        terminal_outcome=WorkflowOutcome.FAILED.value,
        failure_category=FailureCategory.WORKFLOW_DEFINITION.value,
        acceptance_criteria_met=False,
        acceptance_evaluation=evaluate_workflow_acceptance(
            project,
            workflow_acceptance_policy,
            zero_budget_failure_categories,
        ),
    )
    project.save()
    log_event("error", "workflow_failed", project_name=project.project_name, phase=project.phase)


def fail_workflow_when_blocked(
    project: ProjectState,
    *,
    blocked_tasks: list[Task],
    workflow_acceptance_policy: str,
    zero_budget_failure_categories: AbstractSet[str],
    evaluate_workflow_acceptance,
    log_event,
) -> None:
    blocked_task_ids = ", ".join(task.id for task in blocked_tasks)
    project.mark_workflow_finished(
        "failed",
        acceptance_policy=workflow_acceptance_policy,
        terminal_outcome=WorkflowOutcome.FAILED.value,
        failure_category=FailureCategory.WORKFLOW_BLOCKED.value,
        acceptance_criteria_met=False,
        acceptance_evaluation=evaluate_workflow_acceptance(
            project,
            workflow_acceptance_policy,
            zero_budget_failure_categories,
        ),
    )
    project.save()
    log_event(
        "error",
        "workflow_blocked",
        project_name=project.project_name,
        phase=project.phase,
        blocked_task_ids=blocked_task_ids,
    )
    raise AgentExecutionError(
        f"Workflow is blocked because pending tasks have unsatisfied dependencies: {blocked_task_ids}"
    )


def continue_workflow_after_task_failure(
    project: ProjectState,
    *,
    task: Task,
    emit_workflow_progress,
    log_event,
) -> None:
    skipped = project.skip_dependent_tasks(
        task.id,
        f"Skipped because dependency '{task.id}' failed",
    )
    emit_workflow_progress_and_save(
        project,
        task=task,
        emit_workflow_progress=emit_workflow_progress,
    )
    if skipped:
        log_event(
            "warning",
            "dependent_tasks_skipped",
            project_name=project.project_name,
            task_id=task.id,
            skipped_task_ids=list(skipped),
        )


def emit_workflow_progress_and_save(
    project: ProjectState,
    *,
    task: Task,
    emit_workflow_progress,
) -> None:
    emit_workflow_progress(project, task=task)
    project.save()


def fail_workflow_after_task_failure(
    project: ProjectState,
    *,
    failure_category: str,
    workflow_acceptance_policy: str,
    zero_budget_failure_categories: AbstractSet[str],
    evaluate_workflow_acceptance,
    log_event,
) -> None:
    project.mark_workflow_finished(
        "failed",
        acceptance_policy=workflow_acceptance_policy,
        terminal_outcome=WorkflowOutcome.FAILED.value,
        failure_category=failure_category,
        acceptance_criteria_met=False,
        acceptance_evaluation=evaluate_workflow_acceptance(
            project,
            workflow_acceptance_policy,
            zero_budget_failure_categories,
        ),
    )
    project.save()
    log_event("error", "workflow_failed", project_name=project.project_name, phase=project.phase)


def dispatch_task_failure(
    project: ProjectState,
    *,
    task: Task,
    failure_category: str,
    workflow_failure_policy: str,
    workflow_acceptance_policy: str,
    zero_budget_failure_categories: AbstractSet[str],
    is_repairable_failure,
    queue_active_cycle_repair,
    emit_workflow_progress,
    evaluate_workflow_acceptance,
    log_event,
) -> Literal["continue", "raise"]:
    if project.should_retry_task(task.id):
        emit_workflow_progress_and_save(
            project,
            task=task,
            emit_workflow_progress=emit_workflow_progress,
        )
        return "continue"
    if not is_repairable_failure(failure_category):
        if workflow_failure_policy == "continue":
            continue_workflow_after_task_failure(
                project,
                task=task,
                emit_workflow_progress=emit_workflow_progress,
                log_event=log_event,
            )
            return "continue"
        fail_workflow_after_task_failure(
            project,
            failure_category=failure_category,
            workflow_acceptance_policy=workflow_acceptance_policy,
            zero_budget_failure_categories=zero_budget_failure_categories,
            evaluate_workflow_acceptance=evaluate_workflow_acceptance,
            log_event=log_event,
        )
        return "raise"
    if queue_active_cycle_repair(project, task):
        emit_workflow_progress_and_save(
            project,
            task=task,
            emit_workflow_progress=emit_workflow_progress,
        )
        return "continue"
    if workflow_failure_policy == "continue":
        continue_workflow_after_task_failure(
            project,
            task=task,
            emit_workflow_progress=emit_workflow_progress,
            log_event=log_event,
        )
        return "continue"
    fail_workflow_after_task_failure(
        project,
        failure_category=failure_category,
        workflow_acceptance_policy=workflow_acceptance_policy,
        zero_budget_failure_categories=zero_budget_failure_categories,
        evaluate_workflow_acceptance=evaluate_workflow_acceptance,
        log_event=log_event,
    )
    return "raise"


def execute_workflow_task(
    project: ProjectState,
    *,
    task: Task,
    run_task,
    exit_if_workflow_cancelled,
    exit_if_workflow_paused,
    classify_task_failure,
    dispatch_task_failure,
    emit_workflow_progress,
) -> Literal["continue", "return"]:
    if exit_if_workflow_cancelled(project):
        return "return"
    if exit_if_workflow_paused(project):
        return "return"
    try:
        run_task(task, project)
    except Exception as exc:
        if exit_if_workflow_cancelled(project):
            return "return"
        failure_category = classify_task_failure(task, exc)
        if (
            dispatch_task_failure(
                project,
                task=task,
                failure_category=failure_category,
            )
            == "continue"
        ):
            return "continue"
        raise exc
    emit_workflow_progress_and_save(
        project,
        task=task,
        emit_workflow_progress=emit_workflow_progress,
    )
    return "continue"


def execute_runnable_tasks(
    project: ProjectState,
    runnable_tasks: list[Task],
    *,
    execute_workflow_task,
) -> bool:
    for task in runnable_tasks:
        if execute_workflow_task(project, task=task) == "return":
            return True
    return False


def execute_runnable_frontier(
    project: ProjectState,
    *,
    runnable_tasks,
    blocked_tasks,
    execute_runnable_tasks,
    workflow_acceptance_policy: str,
    zero_budget_failure_categories: AbstractSet[str],
    evaluate_workflow_acceptance,
    log_event,
) -> bool:
    try:
        runnable = runnable_tasks()
    except WorkflowDefinitionError:
        fail_workflow_for_definition_error(
            project,
            workflow_acceptance_policy=workflow_acceptance_policy,
            zero_budget_failure_categories=zero_budget_failure_categories,
            evaluate_workflow_acceptance=evaluate_workflow_acceptance,
            log_event=log_event,
        )
        raise
    if not runnable:
        fail_workflow_when_blocked(
            project,
            blocked_tasks=list(blocked_tasks()),
            workflow_acceptance_policy=workflow_acceptance_policy,
            zero_budget_failure_categories=zero_budget_failure_categories,
            evaluate_workflow_acceptance=evaluate_workflow_acceptance,
            log_event=log_event,
        )
    return execute_runnable_tasks(project, runnable)


def execute_workflow_loop(
    project: ProjectState,
    *,
    exit_if_workflow_cancelled,
    exit_if_workflow_paused,
    pending_tasks,
    finish_workflow_if_no_pending_tasks,
    execute_runnable_frontier,
) -> bool:
    while True:
        if exit_if_workflow_cancelled(project):
            return True
        pending = pending_tasks()
        if finish_workflow_if_no_pending_tasks(project, pending):
            return False
        if exit_if_workflow_cancelled(project):
            return True
        if exit_if_workflow_paused(project):
            return True
        if execute_runnable_frontier(project):
            return True


def run_active_workflow(
    project: ProjectState,
    *,
    exit_if_workflow_cancelled,
    exit_if_workflow_paused,
    ensure_workflow_running,
    execute_workflow_loop,
    log_event,
) -> bool:
    if exit_if_workflow_cancelled(project):
        return True
    if exit_if_workflow_paused(project):
        return True
    ensure_workflow_running(project)
    if execute_workflow_loop(project):
        return True
    log_event(
        "info",
        "workflow_finished",
        project_name=project.project_name,
        phase=project.phase,
        terminal_outcome=project.terminal_outcome,
        workflow_telemetry=project.internal_runtime_telemetry()["workflow"],
    )
    return False


def prepare_workflow_execution(
    project: ProjectState,
    *,
    exit_if_workflow_cancelled,
    execution_plan,
    validate_agent_resolution,
    registry,
    workflow_max_repair_cycles: int,
    resume_workflow_tasks,
    run_active_workflow,
) -> bool:
    if exit_if_workflow_cancelled(project):
        return True
    execution_plan()
    validate_agent_resolution(registry, project)
    project.repair_max_cycles = workflow_max_repair_cycles
    resume_workflow_tasks(project)
    return run_active_workflow(project)


def execute_workflow_runtime(
    project: ProjectState,
    *,
    exit_if_workflow_cancelled,
    execution_plan,
    validate_agent_resolution,
    registry,
    workflow_max_repair_cycles: int,
    resume_workflow_tasks,
    run_active_workflow,
) -> None:
    if prepare_workflow_execution(
        project,
        exit_if_workflow_cancelled=exit_if_workflow_cancelled,
        execution_plan=execution_plan,
        validate_agent_resolution=validate_agent_resolution,
        registry=registry,
        workflow_max_repair_cycles=workflow_max_repair_cycles,
        resume_workflow_tasks=resume_workflow_tasks,
        run_active_workflow=run_active_workflow,
    ):
        return


def build_repair_context(
    task: Task,
    cycle: dict[str, Any],
    *,
    repair_owner_for_category: Callable[[Task, str], str],
    build_repair_instruction: Callable[[Task, str], str],
    build_repair_validation_summary: Callable[[Task, str], str],
    failed_artifact_content_for_category: Callable[[Task, str], str],
    test_repair_helper_surface_usages: Callable[[Task, str], list[str]],
    normalized_helper_surface_symbols: Callable[[object], list[str]],
    merge_prior_repair_context: Callable[[Task, dict[str, Any]], None],
) -> dict[str, Any]:
    failure_category = task.last_error_category or FailureCategory.UNKNOWN.value
    repair_context: dict[str, Any] = {
        "cycle": cycle.get("cycle"),
        "failure_category": failure_category,
        "failure_message": task.last_error or task.output or "",
        "failure_error_type": task.last_error_type,
        "repair_owner": repair_owner_for_category(task, failure_category),
        "original_assigned_to": task.assigned_to,
        "instruction": build_repair_instruction(task, failure_category),
        "validation_summary": build_repair_validation_summary(task, failure_category),
        "failed_output": task.output or "",
        "failed_artifact_content": failed_artifact_content_for_category(task, failure_category),
        "provider_call": task.last_provider_call,
    }
    helper_surface_usages = test_repair_helper_surface_usages(task, failure_category)
    if helper_surface_usages:
        repair_context["helper_surface_usages"] = helper_surface_usages
        repair_context["helper_surface_symbols"] = normalized_helper_surface_symbols(
            helper_surface_usages
        )
    merge_prior_repair_context(task, repair_context)
    return repair_context


def build_repair_context_runtime(task: Task, cycle: dict[str, Any]) -> dict[str, Any]:
    def current_repair_owner_for_category(current_task: Task, failure_category: str) -> str:
        return repair_owner_for_category(
            current_task.assigned_to,
            failure_category,
        )

    def current_repair_instruction(current_task: Task, failure_category: str) -> str:
        return build_repair_instruction_runtime(
            current_task,
            failure_category,
            failed_artifact_content=failed_artifact_content,
            artifact_type=AgentOutputArtifactType.CODE,
            validation_payload=validation_payload,
            dataclass_default_order_repair_examples=dataclass_default_order_repair_examples,
            missing_import_nameerror_details=missing_import_nameerror_details,
            plain_class_field_default_factory_details=plain_class_field_default_factory_details,
            test_validation_has_only_warnings=validation_has_only_warnings,
        )

    def current_repair_validation_summary(current_task: Task, failure_category: str) -> str:
        return build_repair_validation_summary(
            current_task,
            failure_category,
            validation_payload(current_task),
        )

    def current_failed_artifact_content_for_category(current_task: Task, failure_category: str) -> str:
        return failed_artifact_content_for_category(
            current_task.output,
            current_task.output_payload,
            failure_category,
        )

    def current_test_repair_helper_surface_usages(current_task: Task, failure_category: str) -> list[str]:
        return helper_surface_usages_for_test_repair_runtime(
            current_task,
            failure_category,
            validation_payload=validation_payload,
        )

    return build_repair_context(
        task,
        cycle,
        repair_owner_for_category=current_repair_owner_for_category,
        build_repair_instruction=current_repair_instruction,
        build_repair_validation_summary=current_repair_validation_summary,
        failed_artifact_content_for_category=current_failed_artifact_content_for_category,
        test_repair_helper_surface_usages=current_test_repair_helper_surface_usages,
        normalized_helper_surface_symbols=normalized_helper_surface_symbols,
        merge_prior_repair_context=merge_prior_repair_context,
    )


def build_code_repair_context_from_test_failure(
    code_task: Task,
    test_task: Task,
    cycle: dict[str, Any],
    *,
    failed_artifact_content: Callable[[Task, Any], str],
    build_repair_validation_summary: Callable[[Task, str], str],
    build_code_repair_instruction_from_test_failure: Callable[[Task, str, object], str],
    merge_prior_repair_context: Callable[[Task, dict[str, Any]], None],
) -> dict[str, Any]:
    existing_tests = failed_artifact_content(test_task, AgentOutputArtifactType.TEST)
    validation_summary = build_repair_validation_summary(
        test_task,
        FailureCategory.TEST_VALIDATION.value,
    )
    repair_context: dict[str, Any] = {
        "cycle": cycle.get("cycle"),
        "failure_category": FailureCategory.CODE_VALIDATION.value,
        "failure_message": test_task.last_error or test_task.output or "",
        "failure_error_type": test_task.last_error_type,
        "repair_owner": "code_engineer",
        "original_assigned_to": code_task.assigned_to,
        "source_failure_task_id": test_task.id,
        "source_failure_category": test_task.last_error_category or FailureCategory.TEST_VALIDATION.value,
        "instruction": build_code_repair_instruction_from_test_failure(
            code_task,
            validation_summary,
            existing_tests,
        ),
        "validation_summary": validation_summary,
        "existing_tests": existing_tests,
        "failed_output": code_task.output or "",
        "failed_artifact_content": failed_artifact_content(code_task, AgentOutputArtifactType.CODE),
        "provider_call": code_task.last_provider_call,
    }
    merge_prior_repair_context(code_task, repair_context)
    return repair_context


def build_code_repair_context_from_test_failure_runtime(
    code_task: Task,
    test_task: Task,
    cycle: dict[str, Any],
) -> dict[str, Any]:
    def current_failed_artifact_content(current_task: Task, artifact_type: Any) -> str:
        return failed_artifact_content(
            current_task.output,
            current_task.output_payload,
            artifact_type,
        )

    def current_repair_validation_summary(current_task: Task, failure_category: str) -> str:
        return build_repair_validation_summary(
            current_task,
            failure_category,
            validation_payload(current_task),
        )

    def current_code_repair_instruction(
        current_code_task: Task,
        validation_summary: str,
        existing_tests: object,
    ) -> str:
        return build_code_repair_instruction_from_test_failure_runtime(
            current_code_task,
            validation_summary,
            failed_artifact_content=current_failed_artifact_content,
            artifact_type=AgentOutputArtifactType.CODE,
            duplicate_constructor_argument_details=duplicate_constructor_argument_details,
            duplicate_constructor_argument_call_hint=duplicate_constructor_argument_call_hint,
            duplicate_constructor_explicit_rewrite_hint=duplicate_constructor_explicit_rewrite_hint,
            plain_class_field_default_factory_details=plain_class_field_default_factory_details,
            missing_object_attribute_details=missing_object_attribute_details,
            suggest_declared_attribute_replacement=suggest_declared_attribute_replacement,
            render_name_list=render_name_list,
            nested_payload_wrapper_field_validation_details=nested_payload_wrapper_field_validation_details,
            invalid_outcome_missing_audit_trail_details=invalid_outcome_missing_audit_trail_details,
            internal_constructor_strictness_details=internal_constructor_strictness_details,
            existing_tests=existing_tests,
        )

    return build_code_repair_context_from_test_failure(
        code_task,
        test_task,
        cycle,
        failed_artifact_content=current_failed_artifact_content,
        build_repair_validation_summary=current_repair_validation_summary,
        build_code_repair_instruction_from_test_failure=current_code_repair_instruction,
        merge_prior_repair_context=merge_prior_repair_context,
    )


def merge_prior_repair_context(task: Task, repair_context: dict[str, Any]) -> None:
    if not isinstance(repair_context, dict) or not task.repair_origin_task_id:
        return

    prior_repair_context = task.repair_context if isinstance(task.repair_context, dict) else {}
    if not prior_repair_context:
        return

    current_instruction = str(repair_context.get("instruction") or "").strip()
    prior_instruction = str(prior_repair_context.get("instruction") or "").strip()
    if prior_instruction and prior_instruction not in current_instruction:
        merged_instruction_parts = [current_instruction] if current_instruction else []
        merged_instruction_parts.append(
            f"Also preserve and fully satisfy the prior unresolved repair objective from {task.repair_origin_task_id}: {prior_instruction}"
        )
        repair_context["instruction"] = " ".join(merged_instruction_parts).strip()

    current_validation_summary = str(repair_context.get("validation_summary") or "").strip()
    prior_validation_summary = str(prior_repair_context.get("validation_summary") or "").strip()
    if prior_validation_summary and prior_validation_summary not in current_validation_summary:
        merged_validation_parts = [current_validation_summary] if current_validation_summary else []
        merged_validation_parts.extend(
            [
                "",
                "Prior unresolved repair context:",
                f"- Prior failure category: {prior_repair_context.get('failure_category') or FailureCategory.UNKNOWN.value}",
            ]
        )
        if prior_instruction:
            merged_validation_parts.append(f"- Prior repair objective: {prior_instruction}")
        merged_validation_parts.extend([
            "- Prior validation summary:",
            prior_validation_summary,
        ])
        repair_context["validation_summary"] = "\n".join(merged_validation_parts).strip()


def exit_if_workflow_paused(logger: Any, project: ProjectState) -> bool:
    if not project.is_workflow_paused():
        return False
    project.save()
    log_event(
        logger,
        "info",
        "workflow_paused",
        project_name=project.project_name,
        phase=project.phase,
        reason=project.workflow_pause_reason,
    )
    return True


def exit_if_workflow_cancelled(logger: Any, project: ProjectState) -> bool:
    if not project.is_workflow_cancelled():
        return False
    project.save()
    log_event(
        logger,
        "warning",
        "workflow_cancelled",
        project_name=project.project_name,
        phase=project.phase,
        terminal_outcome=project.terminal_outcome,
    )
    return True


def validate_agent_resolution(registry: Any, project: ProjectState) -> None:
    for task in project.tasks:
        if not registry.has(task.assigned_to):
            raise AgentExecutionError(
                f"Task '{task.id}' is assigned to unknown agent '{task.assigned_to}'"
            )