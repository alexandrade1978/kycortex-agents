"""Workflow-control helpers used by the Orchestrator facade."""

from __future__ import annotations

from typing import Any, Callable, Optional, cast

from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.providers.base import redact_sensitive_data
from kycortex_agents.types import AgentOutput, ArtifactType as AgentOutputArtifactType, FailureCategory


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


def active_repair_cycle(project: ProjectState) -> dict[str, Any] | None:
    if not project.repair_history:
        return None
    current_cycle = project.repair_history[-1]
    if not isinstance(current_cycle, dict):
        return None
    return current_cycle


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